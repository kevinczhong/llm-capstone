"""
EDI X12 850 Purchase Order to OMS JSON Translation Service
Based on TG-MAP-850-V4.2 specification
"""

import re
import json
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta


# Code lookup tables
TRANSACTION_PURPOSE = {
    "00": "ORIGINAL",
    "01": "CANCEL",
    "04": "CHANGE",
    "07": "DUPLICATE",
    "22": "INFO_ONLY",
}

PO_TYPE = {
    "DS": "DROPSHIP",
    "SA": "STANDALONE",
    "NE": "NEW_ORDER",
}

UOM_CODES = {
    "EA": "EACH",
    "CA": "CASE",
    "DZ": "DOZEN",
    "KG": "KG",
}

FOB_PAYMENT = {
    "PP": "PREPAID",
    "CC": "COLLECT",
}

SAC_TYPE = {
    "A": "ALLOWANCE",
    "C": "CHARGE",
}

SAC_METHOD = {
    "02": "OFF_INVOICE",
    "06": "CHARGE_TO_BE_PAID",
}

SLN_TYPE = {
    "I": "Included",
    "O": "Option",
}

ADDRESS_TYPE_MAP = {
    "ST": "shipTo",
    "BT": "billTo",
    "VN": "vendorDetails",
    "BY": "buyer",
    "MA": "markFor",
}

PRODUCT_ID_MAP = {
    "UP": "upc",
    "VN": "vendorPartNumber",
    "BP": "buyerPartNumber",
    "EN": "ean",
    "SK": "sku",
}


@dataclass
class EDIDelimiters:
    """EDI delimiter configuration parsed from ISA segment."""
    segment: str = "~"
    element: str = "*"
    subelement: str = ">"


@dataclass
class ValidationError:
    """Represents a validation error."""
    code: str
    message: str
    segment: Optional[str] = None


@dataclass
class TranslationResult:
    """Result of EDI translation."""
    success: bool
    data: Optional[dict] = None
    errors: list = field(default_factory=list)


class EDI850Parser:
    """Parses raw EDI X12 850 content into segments."""

    def __init__(self, raw_content: str):
        self.raw = raw_content.strip()
        self.delimiters = self._parse_delimiters()
        self.segments = self._parse_segments()

    def _parse_delimiters(self) -> EDIDelimiters:
        """Extract delimiters from ISA segment (fixed positions)."""
        if not self.raw.startswith("ISA"):
            raise ValueError("Invalid EDI: must start with ISA segment")

        # ISA is fixed-length: element separator at position 3
        element_sep = self.raw[3]

        # Subelement separator is at ISA16 (position 104)
        # Segment terminator follows ISA16
        isa_end = 105 + 1  # ISA is 106 chars including terminator
        subelement_sep = self.raw[104] if len(self.raw) > 104 else ">"
        segment_term = self.raw[105] if len(self.raw) > 105 else "~"

        return EDIDelimiters(
            segment=segment_term,
            element=element_sep,
            subelement=subelement_sep
        )

    def _parse_segments(self) -> list[list[str]]:
        """Split EDI into segments and elements."""
        segments = []
        for seg in self.raw.split(self.delimiters.segment):
            seg = seg.strip()
            if seg:
                elements = seg.split(self.delimiters.element)
                segments.append(elements)
        return segments

    def get_segments_by_type(self, seg_type: str) -> list[list[str]]:
        """Get all segments of a specific type."""
        return [s for s in self.segments if s and s[0] == seg_type]

    def get_segment(self, seg_type: str) -> Optional[list[str]]:
        """Get first segment of a specific type."""
        segs = self.get_segments_by_type(seg_type)
        return segs[0] if segs else None


class EDI850Translator:
    """Translates EDI X12 850 to OMS JSON format."""

    def __init__(self):
        self.errors: list[ValidationError] = []

    def translate(self, edi_content: str) -> TranslationResult:
        """Main translation entry point."""
        self.errors = []

        try:
            parser = EDI850Parser(edi_content)
        except ValueError as e:
            return TranslationResult(
                success=False,
                errors=[ValidationError("PARSE_ERROR", str(e))]
            )

        result = {
            "meta": {},
            "order": {
                "lines": [],
                "chargesAndAllowances": [],
                "customAttributes": [],
            },
            "shipping": {},
        }

        # Map header segments
        self._map_isa(parser, result)
        self._map_gs(parser, result)
        self._map_st(parser, result)
        self._map_beg(parser, result)
        self._map_cur(parser, result)
        self._map_ref(parser, result)
        self._map_per(parser, result)
        self._map_fob(parser, result)
        self._map_header_sac(parser, result)
        self._map_addresses(parser, result)

        # Map line items
        self._map_line_items(parser, result)

        # Map summary
        self._map_ctt(parser, result)
        self._map_amt(parser, result)
        self._map_se(parser, result)

        # Validate
        self._validate(result)

        # Clean up empty structures
        self._cleanup(result)

        if self.errors:
            critical = [e for e in self.errors if e.code.startswith("MISSING")]
            if critical:
                return TranslationResult(success=False, data=result, errors=self.errors)

        return TranslationResult(success=True, data=result, errors=self.errors)

    def _get_element(self, segment: list[str], index: int, default: str = "") -> str:
        """Safely get element from segment."""
        if segment and len(segment) > index:
            return segment[index].strip()
        return default

    def _convert_date(self, date_str: str) -> str:
        """Convert CCYYMMDD to YYYY-MM-DD."""
        if not date_str or len(date_str) != 8:
            return ""
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if needed."""
        if len(text) <= max_len:
            return text
        return text[:max_len-3] + "..."

    def _map_isa(self, parser: EDI850Parser, result: dict):
        """Map ISA segment to meta."""
        isa = parser.get_segment("ISA")
        if not isa:
            self.errors.append(ValidationError("MISSING_ISA", "ISA segment required"))
            return

        result["meta"]["senderId"] = self._get_element(isa, 6).strip()
        result["meta"]["receiverId"] = self._get_element(isa, 8).strip()
        # Preserve leading zeros for control number
        result["meta"]["interchangeControlNumber"] = self._get_element(isa, 13)

    def _map_gs(self, parser: EDI850Parser, result: dict):
        """Map GS segment to meta."""
        gs = parser.get_segment("GS")
        if not gs:
            self.errors.append(ValidationError("MISSING_GS", "GS segment required"))
            return

        result["meta"]["groupControlNumber"] = self._get_element(gs, 6)

        version = self._get_element(gs, 8)
        result["meta"]["ediVersion"] = version
        if version != "004010":
            self.errors.append(ValidationError(
                "INVALID_VERSION",
                f"Expected version 004010, got {version}",
                "GS"
            ))

    def _map_st(self, parser: EDI850Parser, result: dict):
        """Map ST segment to meta."""
        st = parser.get_segment("ST")
        if not st:
            self.errors.append(ValidationError("MISSING_ST", "ST segment required"))
            return

        result["meta"]["transactionType"] = "850"  # Hardcoded per spec
        result["meta"]["transactionControlNumber"] = self._get_element(st, 2)

    def _map_beg(self, parser: EDI850Parser, result: dict):
        """Map BEG segment to order."""
        beg = parser.get_segment("BEG")
        if not beg:
            self.errors.append(ValidationError("MISSING_BEG", "BEG segment required"))
            return

        # BEG01 - Transaction Purpose
        purpose = self._get_element(beg, 1)
        result["order"]["type"] = TRANSACTION_PURPOSE.get(purpose, purpose)

        # BEG02 - PO Type
        po_type = self._get_element(beg, 2)
        result["order"]["category"] = PO_TYPE.get(po_type, po_type)

        # BEG03 - PO Number (mandatory)
        po_number = self._get_element(beg, 3)
        if not po_number:
            self.errors.append(ValidationError(
                "MISSING_PO_NUMBER",
                "BEG03 (PO Number) is mandatory",
                "BEG"
            ))
        result["order"]["poNumber"] = self._truncate(po_number.strip(), 22)

        # BEG05 - PO Date (mandatory)
        po_date = self._get_element(beg, 5)
        if not po_date:
            self.errors.append(ValidationError(
                "MISSING_PO_DATE",
                "BEG05 (PO Date) is mandatory",
                "BEG"
            ))
        result["order"]["orderDate"] = self._convert_date(po_date)

    def _map_cur(self, parser: EDI850Parser, result: dict):
        """Map CUR segment to order currency."""
        cur = parser.get_segment("CUR")
        currency = "USD"  # Default per spec
        if cur:
            currency = self._get_element(cur, 2) or "USD"
        result["order"]["currencyCode"] = currency
        result["meta"]["currency"] = currency

    def _map_ref(self, parser: EDI850Parser, result: dict):
        """Map REF segments based on qualifier."""
        ref_map = {
            "VR": "vendorId",
            "DP": "departmentId",
            "PD": "promotionId",
            "IA": "internalVendorId",
        }

        for ref in parser.get_segments_by_type("REF"):
            qualifier = self._get_element(ref, 1)
            value = self._get_element(ref, 2)

            if qualifier in ref_map:
                result["order"][ref_map[qualifier]] = value
            elif qualifier == "ZZ":
                result["order"]["customAttributes"].append({
                    "key": self._get_element(ref, 3) or "custom",
                    "value": value
                })

    def _map_per(self, parser: EDI850Parser, result: dict):
        """Map PER segment to contact info."""
        per = parser.get_segment("PER")
        if not per:
            return

        contact = {}
        contact["name"] = self._get_element(per, 2)

        # PER03/04 - Communication qualifier and number
        comm_qual = self._get_element(per, 3)
        comm_num = self._get_element(per, 4)

        if comm_qual == "TE":
            contact["phone"] = comm_num
        elif comm_qual == "EM":
            contact["email"] = comm_num

        # PER05/06 - Secondary communication
        if len(per) > 6:
            comm_qual2 = self._get_element(per, 5)
            comm_num2 = self._get_element(per, 6)
            if comm_qual2 == "TE":
                contact["phone"] = comm_num2
            elif comm_qual2 == "EM":
                contact["email"] = comm_num2

        if contact:
            result["order"]["contact"] = contact

    def _map_fob(self, parser: EDI850Parser, result: dict):
        """Map FOB segment to shipping."""
        fob = parser.get_segment("FOB")
        if not fob:
            return

        payment = self._get_element(fob, 1)
        result["shipping"]["paymentMethod"] = FOB_PAYMENT.get(payment, payment)

        location = self._get_element(fob, 2)
        if location:
            result["shipping"]["fobPoint"] = location

    def _map_header_sac(self, parser: EDI850Parser, result: dict):
        """Map header-level SAC segments."""
        # Header SAC comes before PO1 lines
        in_header = True
        for seg in parser.segments:
            if seg[0] == "PO1":
                in_header = False
            if seg[0] == "SAC" and in_header:
                self._map_sac_segment(seg, result["order"]["chargesAndAllowances"])

    def _map_sac_segment(self, sac: list[str], target: list):
        """Map a single SAC segment."""
        charge = {}

        indicator = self._get_element(sac, 1)
        charge["type"] = SAC_TYPE.get(indicator, indicator)

        charge["code"] = self._get_element(sac, 2)

        amount = self._get_element(sac, 5)
        if amount:
            try:
                charge["amount"] = float(amount)
            except ValueError:
                charge["amount"] = amount

        method = self._get_element(sac, 12)
        if method:
            charge["method"] = SAC_METHOD.get(method, method)

        desc = self._get_element(sac, 15)
        if desc:
            charge["description"] = desc

        target.append(charge)

    def _map_addresses(self, parser: EDI850Parser, result: dict):
        """Map N1 loop (N1/N2/N3/N4) addresses."""
        current_address = None
        current_type = None

        for seg in parser.segments:
            seg_type = seg[0] if seg else ""

            if seg_type == "N1":
                # Save previous address
                if current_address and current_type:
                    result["order"][current_type] = current_address

                # Start new address
                type_code = self._get_element(seg, 1)
                current_type = ADDRESS_TYPE_MAP.get(type_code)

                if current_type:
                    current_address = {
                        "name": self._get_element(seg, 2),
                        "idQualifier": self._get_element(seg, 3),
                        "id": self._get_element(seg, 4),
                    }
                else:
                    current_address = None

            elif seg_type == "N2" and current_address:
                current_address["additionalName"] = self._get_element(seg, 1)

            elif seg_type == "N3" and current_address:
                current_address["address"] = {
                    "line1": self._truncate(self._get_element(seg, 1), 35),
                    "line2": self._truncate(self._get_element(seg, 2), 35),
                }

            elif seg_type == "N4" and current_address:
                if "address" not in current_address:
                    current_address["address"] = {}
                current_address["address"]["city"] = self._get_element(seg, 1)
                current_address["address"]["state"] = self._get_element(seg, 2)
                current_address["address"]["postalCode"] = self._get_element(seg, 3)
                current_address["address"]["country"] = self._get_element(seg, 4)

        # Save last address
        if current_address and current_type:
            result["order"][current_type] = current_address

    def _map_line_items(self, parser: EDI850Parser, result: dict):
        """Map PO1 lines and related segments."""
        current_line = None
        line_index = -1

        for seg in parser.segments:
            seg_type = seg[0] if seg else ""

            if seg_type == "PO1":
                # Save previous line
                if current_line is not None:
                    result["order"]["lines"].append(current_line)

                line_index += 1
                current_line = self._parse_po1(seg)

            elif seg_type == "PID" and current_line is not None:
                self._parse_pid(seg, current_line)

            elif seg_type == "PO4" and current_line is not None:
                self._parse_po4(seg, current_line)

            elif seg_type == "SAC" and current_line is not None:
                if "lineCharges" not in current_line:
                    current_line["lineCharges"] = []
                self._map_sac_segment(seg, current_line["lineCharges"])

            elif seg_type == "SLN" and current_line is not None:
                self._parse_sln(seg, current_line)

        # Save last line
        if current_line is not None:
            result["order"]["lines"].append(current_line)

    def _parse_po1(self, po1: list[str]) -> dict:
        """Parse PO1 segment into line item."""
        line = {}

        # PO101 - Line Number
        line_num = self._get_element(po1, 1)
        try:
            line["lineNumber"] = int(line_num)
        except ValueError:
            line["lineNumber"] = line_num

        # PO102 - Quantity (mandatory)
        qty = self._get_element(po1, 2)
        if not qty:
            self.errors.append(ValidationError(
                "MISSING_QUANTITY",
                f"PO102 (Quantity) is mandatory for line {line_num}",
                "PO1"
            ))
        try:
            line["quantity"] = int(qty) if qty else 0
        except ValueError:
            line["quantity"] = qty

        # PO103 - UOM (mandatory)
        uom = self._get_element(po1, 3)
        if not uom:
            self.errors.append(ValidationError(
                "MISSING_UOM",
                f"PO103 (UOM) is mandatory for line {line_num}",
                "PO1"
            ))
        line["uom"] = UOM_CODES.get(uom, uom)

        # PO104 - Unit Price
        price = self._get_element(po1, 4)
        if price:
            try:
                line["unitPrice"] = float(price)
            except ValueError:
                line["unitPrice"] = price

        # Product ID pairs (PO106-07, PO108-09, etc.)
        idx = 6
        while idx + 1 < len(po1):
            qualifier = self._get_element(po1, idx)
            value = self._get_element(po1, idx + 1)

            if qualifier and value:
                json_key = PRODUCT_ID_MAP.get(qualifier)
                if json_key:
                    line[json_key] = value

            idx += 2

        return line

    def _parse_pid(self, pid: list[str], line: dict):
        """Parse PID segment and add to line."""
        desc = self._get_element(pid, 5)
        if desc:
            desc = self._truncate(desc, 100)
            if "description" in line:
                line["description"] += " " + desc
            else:
                line["description"] = desc

        # Special codes for color/size
        item_char = self._get_element(pid, 2)
        if item_char == "73":
            line["color"] = desc
        elif item_char == "74":
            line["size"] = desc

    def _parse_po4(self, po4: list[str], line: dict):
        """Parse PO4 segment (physical details)."""
        pack = self._get_element(po4, 1)
        if pack:
            try:
                line["packSize"] = int(pack)
            except ValueError:
                line["packSize"] = pack

        inner = self._get_element(po4, 14)
        if inner:
            try:
                line["innerPack"] = int(inner)
            except ValueError:
                line["innerPack"] = inner

    def _parse_sln(self, sln: list[str], line: dict):
        """Parse SLN segment (sub-line for kits)."""
        if "components" not in line:
            line["components"] = []

        component = {
            "id": self._get_element(sln, 1),
            "type": SLN_TYPE.get(self._get_element(sln, 3), self._get_element(sln, 3)),
        }

        qty = self._get_element(sln, 4)
        if qty:
            try:
                component["qty"] = int(qty)
            except ValueError:
                component["qty"] = qty

        sku = self._get_element(sln, 9)
        if sku:
            component["sku"] = sku

        line["components"].append(component)

    def _map_ctt(self, parser: EDI850Parser, result: dict):
        """Map CTT segment for validation."""
        ctt = parser.get_segment("CTT")
        if not ctt:
            return

        if "validation" not in result["meta"]:
            result["meta"]["validation"] = {}

        line_count = self._get_element(ctt, 1)
        if line_count:
            try:
                result["meta"]["validation"]["lineCount"] = int(line_count)
            except ValueError:
                result["meta"]["validation"]["lineCount"] = line_count

        hash_total = self._get_element(ctt, 2)
        if hash_total:
            try:
                result["meta"]["validation"]["hashTotal"] = int(hash_total)
            except ValueError:
                result["meta"]["validation"]["hashTotal"] = hash_total

    def _map_amt(self, parser: EDI850Parser, result: dict):
        """Map AMT segment."""
        amt = parser.get_segment("AMT")
        if not amt:
            return

        amount = self._get_element(amt, 2)
        if amount:
            try:
                result["order"]["totalAmount"] = float(amount)
            except ValueError:
                result["order"]["totalAmount"] = amount

    def _map_se(self, parser: EDI850Parser, result: dict):
        """Map SE segment for validation."""
        se = parser.get_segment("SE")
        if not se:
            return

        if "validation" not in result["meta"]:
            result["meta"]["validation"] = {}

        seg_count = self._get_element(se, 1)
        if seg_count:
            try:
                result["meta"]["validation"]["segmentCount"] = int(seg_count)
            except ValueError:
                result["meta"]["validation"]["segmentCount"] = seg_count

        trailer_ctrl = self._get_element(se, 2)
        result["meta"]["validation"]["trailerControlNumber"] = trailer_ctrl

        # Validate trailer matches ST02
        st_ctrl = result["meta"].get("transactionControlNumber")
        if st_ctrl and trailer_ctrl and st_ctrl != trailer_ctrl:
            self.errors.append(ValidationError(
                "CONTROL_NUMBER_MISMATCH",
                f"SE02 ({trailer_ctrl}) must match ST02 ({st_ctrl})",
                "SE"
            ))

    def _validate(self, result: dict):
        """Perform business validations."""
        order = result.get("order", {})

        # Check mandatory Ship To
        if "shipTo" not in order:
            self.errors.append(ValidationError(
                "MISSING_SHIP_TO",
                "N1-ST (Ship To) loop is mandatory"
            ))

        # Validate date not in future and not older than 365 days
        order_date = order.get("orderDate")
        if order_date:
            try:
                dt = datetime.strptime(order_date, "%Y-%m-%d")
                today = datetime.now()
                if dt > today:
                    self.errors.append(ValidationError(
                        "FUTURE_DATE",
                        f"Order date {order_date} cannot be in the future"
                    ))
                if dt < today - timedelta(days=365):
                    self.errors.append(ValidationError(
                        "DATE_TOO_OLD",
                        f"Order date {order_date} is older than 365 days"
                    ))
            except ValueError:
                pass

        # Validate line count
        validation = result.get("meta", {}).get("validation", {})
        expected_count = validation.get("lineCount")
        actual_count = len(order.get("lines", []))
        if expected_count and expected_count != actual_count:
            self.errors.append(ValidationError(
                "LINE_COUNT_MISMATCH",
                f"CTT01 ({expected_count}) does not match actual lines ({actual_count})"
            ))

    def _cleanup(self, result: dict):
        """Remove empty structures from result."""
        order = result.get("order", {})

        # Remove empty lists
        if not order.get("chargesAndAllowances"):
            order.pop("chargesAndAllowances", None)
        if not order.get("customAttributes"):
            order.pop("customAttributes", None)

        # Remove empty shipping
        if not result.get("shipping"):
            result.pop("shipping", None)


def translate_edi_850(edi_content: str) -> dict:
    """
    Convenience function to translate EDI 850 to OMS JSON.

    Args:
        edi_content: Raw EDI X12 850 content

    Returns:
        Dictionary with 'success', 'data', and 'errors' keys
    """
    translator = EDI850Translator()
    result = translator.translate(edi_content)
    return {
        "success": result.success,
        "data": result.data,
        "errors": [{"code": e.code, "message": e.message, "segment": e.segment}
                   for e in result.errors]
    }


if __name__ == "__main__":
    # Test with sample EDI from specification
    sample_edi = """ISA*00*          *00*          *ZZ*RETAILGIANT    *ZZ*TRANSACTGLOBAL *251024*1030*U*00401*000001005*0*P*>~
GS*PO*RETAILGIANT*TRANSACTGLOBAL*20251024*1030*1005*X*004010~
ST*850*0001~
BEG*00*SA*PO-99887766**20251024~
CUR*SE*USD~
REF*DP*055~
REF*VR*112233~
N1*ST*Seattle Distribution Center*92*0044~
N3*1234 Rainier Ave S*Suite 400~
N4*Seattle*WA*98144*US~
N1*BY*RetailGiant HQ*91*RG-HQ-01~
N3*5000 Commerce Blvd~
N4*New York*NY*10001*US~
PO1*1*100*EA*24.99**UP*123456789012*VN*TG-WIDGET-01*SK*SKU-555~
PID*F****Premium Blue Widget~
PO1*2*50*CA*120.00**UP*987654321098*VN*TG-GADGET-99~
PID*F****Bulk Gadget Pack~
CTT*2*150~
SE*15*0001~
GE*1*1005~
IEA*1*000001005~"""

    result = translate_edi_850(sample_edi)
    print(json.dumps(result, indent=2))
