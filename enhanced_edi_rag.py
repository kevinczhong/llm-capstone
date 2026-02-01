from dotenv import load_dotenv
from langfuse.openai import openai
from langfuse import observe, get_client
# from openai import OpenAI
from pinecone import Pinecone
import json
import os

load_dotenv('.env')

llm = openai
pc = Pinecone(api_key = os.getenv("PINECONE_API_KEY"))
dense_index = pc.Index("edi-spec")
langfuse = get_client()

def search_docs(query, sentiment):
  total_vectors = dense_index.describe_index_stats()['total_vector_count']
  # print(total_vectors)
  # sentiment_k = int(sentiment * 100)
  sentiment_k = int(sentiment * int(total_vectors))
  print(f"Searching with top_k = {sentiment_k}")
  results = dense_index.search(
      namespace= "850_PO_implementation",
      query={
          "top_k": sentiment_k,
          "inputs": {
              'text': query
          }
      }
  )

  documentation = ""
  for hit in results['result']['hits']:
      fields = hit.get('fields')
      chunk_text = fields.get('text')
      documentation += chunk_text

  return documentation

@observe
def sentiment_analysis(query):
    sentiment_clear = False
    while sentiment_clear is False:
      response = llm.responses.create(
          model="gpt-5",
          input=f"""Analyze the sentiment of the following query: {query}. Respond with a decimal betwene 0 and 1,
          where, 0 represents a query sentiment that's the most narrow, and 1 represents a query sentiment that's the most broad.
          """
      )
      try:
        sentiment = float(response.output_text)
        sentiment_clear = True
      except:
        print("Failed to parse sentiment, retrying...")
    return sentiment

def system_prompt(documentation):
    return f'You are an expert EDI systems analyst. Your role is to analyze EDI specifications and provide robust, accurate information to internal technical stakeholders. Respond to user queries solely on the following documentation: {documentation}. If the subject of the user query is not covered in the documentation, say "I cannot answer this question based on the provided documentation."'

# Main conversation loop:
assistant_message = "Hello! I'm EDI Spec Assistant. How may I help you today?"
user_input = input(f"\nAssistant: {assistant_message}\n\nUser: ")

history = [
    {"role": "developer", "content": ""},
    {"role": "assistant", "content": assistant_message},
    {"role": "user", "content": user_input}
]

with langfuse.start_as_current_observation(as_type = "span", name = "podcast-conversation") as span:
  while user_input != "exit":
    sentiment = sentiment_analysis(user_input)
    documentation = search_docs(user_input, sentiment)
    history[0] = {"role": "developer", "content": system_prompt(documentation)}

    response = llm.responses.create(
      model="gpt-5",
      input=history,
    )

    llm_response_text = f"\nAssistant: {response.output_text}"
    print(llm_response_text)

    user_input = input("\nUser: ")
    history += [
      {"role": "assistant", "content": response.output_text},
      {"role": "user", "content": user_input}
    ]
  span.update(output = "Conversation complete.")

langfuse.flush()

# print(sentiment_analysis("Give me a general overview of the 850 PO"))
# print(sentiment_analysis("Does the 850 PO support reporting of Dangerous Goods?"))