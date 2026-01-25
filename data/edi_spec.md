# EDI Implementation Guide: X12 850 Purchase Order to OMS JSON (v4.2)

## Document Control

| Property      | Value                                      |
| ------------- | ------------------------------------------ |
| Document ID   | TG-MAP-850-V4.2                            |
| Project       | RetailGiant Global Integration             |
| Source Format | ANSI X12 850 (Purchase Order) Version 4010 |
| Target Format | TransactGlobal OMS JSON Schema v2.1        |
| Author        | Integration Architecture Team              |
| Last Updated  | October 24, 2025                           |
| Status        | **APPROVED FOR PRODUCTION**                |

## Version History

| Version | Date       | Author   | Description of Changes                                                    |
| ------- | ---------- | -------- | ------------------------------------------------------------------------- |
| 1.0     | 2024-01-15 | J. Doe   | Initial Draft.                                                            |
| 1.5     | 2024-03-10 | M. Smith | Added detailed mapping for PID segments and extended loop logic.          |
| 2.0     | 2024-06-22 | J. Doe   | Updated JSON target schema to v2.0; introduced shipTo object splitting.   |
| 3.1     | 2024-09-05 | A. Patel | Added SDQ (Destination Quantity) segment logic for cross-dock orders.     |
| 4.0     | 2024-12-01 | M. Smith | Major refactor of Allowance/Charge (SAC) logic for header vs. line level. |
| 4.1     | 2025-05-15 | J. Doe   | Correction to Date/Time formatting ISO 8601 compliance rules.             |
| 4.2     | 2025-10-24 | A. Patel | Final validations and inclusion of expanded error codes.                  |

---

## 1. Introduction

### 1.1 Purpose

This document serves as the authoritative mapping specification for the translation of inbound ANSI X12 850 Purchase Orders received from the trading partner (**RetailGiant**) into the internal JSON format required by the **TransactGlobal Order Management System (OMS)**. This specification is designed to be utilized by the middleware integration layer (MuleSoft / Tibco / Boomi) to govern the transformation logic.

### 1.2 Scope

The scope of this document includes:

* **Data Transformation**: Field-level mapping from X12 segments/elements to JSON key-value pairs.
* **Business Logic**: Conditional rules, data normalization, and lookup requirements.
* **Validation**: Syntactic and semantic validation rules for incoming EDI data.
* **Error Handling**: Procedures for malformed or non-compliant EDI transmissions.

This document excludes the outbound acknowledgment (997) process and the subsequent Invoice (810) or ASN (856) mapping specifications, which are detailed in separate documents.

### 1.3 Audience

* **Integration Developers**: Implementing the mapping code.
* **QA Engineers**: Creating test cases and validating output.
* **Business Analysts**: Understanding how business requirements translate to technical specifications.
* **Support Teams**: Troubleshooting production data issues.

---

## 2. Technical Standards & Protocols

### 2.1 EDI Envelope Specifications

The incoming file is expected to adhere to the standard ISA/GS enveloping structure. The translator must parse the envelope to extract routing information but generally does not map envelope data into the JSON business payload, except for Control Numbers used for tracking.

* **Standard**: ANSI X12
* **Version**: 004010
* **Transaction Set**: 850 (Purchase Order)

#### Delimiters

The parser must dynamically read delimiters from the ISA segment; the agreed defaults are:

* **Segment Terminator**: `~`
* **Element Separator**: `*`
* **Sub-element Separator**: `>`

### 2.2 JSON Target Standards

* **Encoding**: UTF-8
* **Date Format**: ISO 8601 (`YYYY-MM-DDThh:mm:ssZ`)
* **Number Format**: No leading zeros; max 4 decimal places. High-precision currency fields should be represented as strings.

---

## 3. General Business Rules

### 3.1 Date and Time Conversion

* **Input**: `CCYYMMDD` (DTM02)
* **Output**: `YYYY-MM-DD`

**Example**:

* Input: `20251024`
* Output: `2025-10-24`

**Logic**:

* If `DTM03` (time) is present, combine date and time.
* If missing, default time to `00:00:00Z`.

### 3.2 Address Parsing

* The N1 loop provides address data.
* Splitting logic is disabled in this version.
* Map:

  * `N301 → address.line1`
  * `N302 → address.line2`

### 3.3 Currency Normalization

* Currency is derived from the `CUR` segment.
* If missing, default currency is `USD`.
* JSON output must populate `meta.currency`.

---

## 4. Mapping Specifications: Header Level

### 4.1 ISA – Interchange Control Header

| Element | Description                | Target JSON Path                | Logic                  |
| ------- | -------------------------- | ------------------------------- | ---------------------- |
| ISA06   | Interchange Sender ID      | `meta.senderId`                 | Trim whitespace        |
| ISA08   | Interchange Receiver ID    | `meta.receiverId`               | Trim whitespace        |
| ISA13   | Interchange Control Number | `meta.interchangeControlNumber` | Preserve leading zeros |

### 4.2 GS – Functional Group Header

| Element | Description          | Target JSON Path          | Logic                    |
| ------- | -------------------- | ------------------------- | ------------------------ |
| GS06    | Group Control Number | `meta.groupControlNumber` | Direct map               |
| GS08    | Version / Release    | `meta.ediVersion`         | Validate equals `004010` |

### 4.3 ST – Transaction Set Header

| Element | Description                 | Target JSON Path                | Logic          |
| ------- | --------------------------- | ------------------------------- | -------------- |
| ST01    | Transaction ID Code         | `meta.transactionType`          | Hardcode `850` |
| ST02    | Transaction Set Control No. | `meta.transactionControlNumber` | Direct map     |

### 4.4 BEG – Beginning Segment for Purchase Order

| Element | Description             | Target JSON Path  | Logic                                      |
| ------- | ----------------------- | ----------------- | ------------------------------------------ |
| BEG01   | Transaction Set Purpose | `order.type`      | 00→ORIGINAL, 01→CANCELLATION, 07→DUPLICATE |
| BEG02   | Purchase Order Type     | `order.category`  | DS→DROPSHIP, SA→STANDALONE, NE→NEW_ORDER   |
| BEG03   | Purchase Order Number   | `order.poNumber`  | Mandatory, trim, max 22                    |
| BEG05   | PO Date                 | `order.orderDate` | Convert CCYYMMDD → YYYY-MM-DD              |

### 4.5 CUR – Currency (Conditional)

| Element | Description   | Target JSON Path     | Logic                    |
| ------- | ------------- | -------------------- | ------------------------ |
| CUR02   | Currency Code | `order.currencyCode` | Default `USD` if missing |

### 4.6 REF – Reference Identification (Header)

Repeatable segment. Mapping based on `REF01` qualifier:

| Qualifier | Description            | Target JSON Path           | Logic                   |
| --------- | ---------------------- | -------------------------- | ----------------------- |
| VR        | Vendor Ref Number      | `order.vendorId`           | Direct map              |
| DP        | Department Number      | `order.departmentId`       | Direct map              |
| PD        | Promotion Deal ID      | `order.promotionId`        | Direct map              |
| IA        | Internal Vendor Number | `order.internalVendorId`   | Direct map              |
| ZZ        | Mutually Defined       | `order.customAttributes[]` | Append `{ key, value }` |

### 4.7 PER – Administrative Communications Contact

| Element | Description          | Target JSON Path            | Logic                   |
| ------- | -------------------- | --------------------------- | ----------------------- |
| PER02   | Name                 | `order.contact.name`        | Direct map              |
| PER03   | Comm Qualifier       | N/A                         | Determines PER04 target |
| PER04   | Communication Number | `order.contact.phone/email` | TE→phone, EM→email      |

### 4.8 FOB – F.O.B. Related Instructions

| Element | Description                | Target JSON Path         | Logic                  |
| ------- | -------------------------- | ------------------------ | ---------------------- |
| FOB01   | Shipment Method of Payment | `shipping.paymentMethod` | PP→PREPAID, CC→COLLECT |
| FOB02   | Location Qualifier         | `shipping.fobPoint`      | ORIGIN / DESTINATION   |

### 4.9 SAC – Allowance / Charge (Header)

Target JSON: `order.chargesAndAllowances[]`

| Element | Description                | Target        | Logic                                |
| ------- | -------------------------- | ------------- | ------------------------------------ |
| SAC01   | Allowance/Charge Indicator | `type`        | A→ALLOWANCE, C→CHARGE                |
| SAC02   | Service/Promo Code         | `code`        | Direct map                           |
| SAC05   | Amount                     | `amount`      | Decimal                              |
| SAC12   | Method                     | `method`      | 02→OFF_INVOICE, 06→CHARGE_TO_BE_PAID |
| SAC15   | Description                | `description` | Direct map                           |

### 4.10 N9 Loop (N1/N2/N3/N4) – Name and Address

Mapping based on `N101`:

| Code | Description  | Target Object         |
| ---- | ------------ | --------------------- |
| ST   | Ship To      | `order.shipTo`        |
| BT   | Bill To      | `order.billTo`        |
| VN   | Vendor       | `order.vendorDetails` |
| BY   | Buying Party | `order.buyer`         |

---

## 5. Mapping Specifications: Detail Level (Line Items)

### 5.1 PO1 – Baseline Item Data

Each `PO1` creates a new `order.lines[]` entry.

| Element | Description | Target       | Logic                      |
| ------- | ----------- | ------------ | -------------------------- |
| PO101   | Line Number | `lineNumber` | Integer                    |
| PO102   | Quantity    | `quantity`   | Integer                    |
| PO103   | UOM         | `uom`        | EA→EACH, CA→CASE, DZ→DOZEN |
| PO104   | Unit Price  | `unitPrice`  | Decimal                    |

**Product ID Iteration**: Iterate qualifier/ID pairs.

* UP → `upc`
* VN → `vendorPartNumber`
* BP → `buyerPartNumber`
* EN → `ean`

### 5.2 PID – Product Description

* Append `PID05` to `lines[].description`.
* Special logic:

  * `73` → color
  * `74` → size

### 5.3 PO4 – Item Physical Details

| Element | Target      | Logic   |
| ------- | ----------- | ------- |
| PO401   | `packSize`  | Integer |
| PO414   | `innerPack` | Integer |

### 5.4 SAC – Allowance / Charge (Line)

Target JSON: `lines[].lineCharges[]` (same logic as header SAC).

### 5.5 SLN – Sub-line Item Detail

Used for kits/assortments.

| Element | Target              | Logic                |
| ------- | ------------------- | -------------------- |
| SLN01   | `components[].id`   | Direct map           |
| SLN03   | `components[].type` | I→Included, O→Option |
| SLN04   | `components[].qty`  | Integer              |
| SLN09   | `components[].sku`  | Direct map           |

---

## 6. Mapping Specifications: Summary Level

### 6.1 CTT – Transaction Totals

| Element | Target                      | Logic                      |
| ------- | --------------------------- | -------------------------- |
| CTT01   | `meta.validation.lineCount` | Validate vs `lines.length` |
| CTT02   | `meta.validation.hashTotal` | Optional quantity sum      |

### 6.2 AMT – Monetary Amount

| Element | Target              | Logic                             |
| ------- | ------------------- | --------------------------------- |
| AMT02   | `order.totalAmount` | Validate against calculated total |

### 6.3 SE – Transaction Set Trailer

| Element | Target                 | Logic                 |
| ------- | ---------------------- | --------------------- |
| SE01    | `segmentCount`         | Validate actual count |
| SE02    | `trailerControlNumber` | Must match `ST02`     |

---

## 7. Code Reference Tables

### Code List A – Transaction Purpose (BEG01)

| X12 | Description      | Internal  |
| --- | ---------------- | --------- |
| 00  | Original         | ORIGINAL  |
| 01  | Cancellation     | CANCEL    |
| 04  | Change           | CHANGE    |
| 07  | Duplicate        | DUPLICATE |
| 22  | Information Copy | INFO_ONLY |

### Code List B – Unit of Measure (PO103)

| X12 | Description | Internal |
| --- | ----------- | -------- |
| EA  | Each        | EACH     |
| CA  | Case        | CASE     |
| DZ  | Dozen       | DOZEN    |
| KG  | Kilogram    | KG       |

### Code List C – Address Types (N101)

| X12 | Description | Internal |
| --- | ----------- | -------- |
| BT  | Bill To     | BILL_TO  |
| ST  | Ship To     | SHIP_TO  |
| BY  | Buyer       | BUYER    |

---

## 8. Error Handling & Validation Logic

* Strict validation enforced.
* Missing critical data results in rejection and negative 997.

### 8.1 Mandatory Fields

* BEG03 (PO Number)
* BEG05 (PO Date)
* N1-ST Loop
* PO102 (Quantity)
* PO103 (UOM)
* PO104 (Price, unless Sample order)

### 8.2 Logic Validations

* **Duplicate Check**: BEG03 vs OMS.
* **Date Validation**: Not future; not older than 365 days.
* **Currency Match**: Must match vendor MDM config.

### 8.3 Data Truncation Rules

* Address lines: max 35 chars.
* Item descriptions: max 100 chars, truncate with `...`.

---

## 9. Appendix: Sample Artifacts

### 9.1 Source EDI (X12 850)

```text
ISA*00* *00* *ZZ*RETAILGIANT    *ZZ*TRANSACTGLOBAL *251024*1030*U*00401*000001005*0*P*>~
GS*PO*RETAILGIANT*TRANSACTGLOBAL*20251024*1030*1005*X*004010~
ST*850*0001~
BEG*00*SA*PO-99887766*20251024~
CUR*SE*USD~
REF*DP*055~
REF*VR*112233~
N1*ST*Seattle Distribution Center*92*0044~
N3*1234 Rainier Ave S*Suite 400~
N4*Seattle*WA*98144*US~
N1*BY*RetailGiant HQ*91*RG-HQ-01~
N3*5000 Commerce Blvd~
N4*New York*NY*10001*US~
PO1*1*100*EA*24.99*UP*123456789012*VN*TG-WIDGET-01*SK*SKU-555~
PID*F****Premium Blue Widget~
PO1*2*50*CA*120.00*UP*987654321098*VN*TG-GADGET-99~
PID*F****Bulk Gadget Pack~
CTT*2*150~
SE*15*0001~
GE*1*1005~
IEA*1*000001005~
```

### 9.2 Target JSON Output

```json
{
  "meta": {
    "senderId": "RETAILGIANT",
    "receiverId": "TRANSACTGLOBAL",
    "interchangeControlNumber": "000001005",
    "groupControlNumber": "1005",
    "ediVersion": "004010",
    "transactionType": "850",
    "transactionControlNumber": "0001"
  }
}
```

---

## 10. Advanced Mapping Scenarios

### 10.1 Drop Ship Orders

* Identified by `BEG02 = DS`.
* Map `N1*ST` to `order.customer`.
* PII must be encrypted if `PII_PROTECTION = true`.

### 10.2 Cross-Dock (Mark-for) Logic

* Use `N1*MA` or `SDQ` segments.
* SDQ requires exploding a single PO1 into multiple JSON lines.

### 10.3 Allowance and Charge Calculations

* Net Price = Base − Allowances + Charges.
* Allowances treated as negative amounts.

---

## 11. Glossary of Terms

* **ANSI X12**: EDI standard
* **Segment**: Line of EDI data
* **Element**: Data point within a segment
* **997 FA**: Functional Acknowledgment
* **OMS**: Order Management System

---

## 12. Implementation Checklist

* [ ] Delimiter parsing verified
* [ ] Loop limits tested
* [ ] UTF-8 encoding validated
* [ ] Date edge cases tested
* [ ] Zero-quantity handling verified
* [ ] JSON Schema v2.1 validation passed
