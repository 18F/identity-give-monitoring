"""
Provides classes representing Elasticsearch queries and functionality for running those queries
against a server and uploading to an index.
"""

from datetime import datetime
from typing import Any
from dateutil import parser
from hashlib import sha256
from opensearchpy import helpers
import analyticsconstants

class AnalyticsQuery:
  """
  The base class for creating objects representing an Elasticsearch query.

  Each AnalyticsQuery object is connected to an Elasticsearch server and can upload documents to
  the dev-analytics-* index pattern.
  """

  def __init__(self, **kwargs):
    self.elasticsearch = kwargs["elasticsearch"]
    self.index_pattern = kwargs["index_pattern"]
    self.query = kwargs["query"]
    self.flow_id = kwargs["flow_id"]
    self.event_message = kwargs["event_message"]
    self.metric = kwargs["metric"]
    self.metric_key = kwargs["metric_key"]
    self.mappings = kwargs["mappings"]
    self.num_composite_buckets = kwargs["num_composite_buckets"] if "num_composite_buckets" in kwargs.keys() else None
    self.document_keys = kwargs["document_keys"] if "document_keys" in kwargs.keys() else None
    self.start_date = self.__convert_start_date_to_int_date(kwargs["start_date"])
    self.end_date = self.__convert_end_date_to_int_date(kwargs["end_date"])

  def __convert_start_date_to_int_date(self, start_date: str) -> int:
    """
    Converts a string formatted start date to an int representing the date.
    """
    if start_date:
      # A start date was provided to the query.
      return int(parser.parse(start_date).timestamp())
    elif not self.elasticsearch.indices.get_alias(f"{self.index_pattern}-*"):
      # A start date was not provided to the query and the dev-analytics index doesn't exist.
      return int((datetime.now() - analyticsconstants.FIVE_MINS).timestamp())
    else:
      # A start date was not provided when running and the dev-analytics index does exist.
      return self.get_most_recent_timestamp()

  def __convert_end_date_to_int_date(self, end_date: str) -> int:
    """
    Converts a string formatted end date to an int representing the date.
    """
    if end_date:
      return int(parser.parse(end_date).timestamp())
    else:
      return int(datetime.now().timestamp())

  def format_query(self):
    """
    Ensures the query performs the composite aggregation on a search of a specific flow id for a
    specific time range.
    """
    pass

  def run_query(self) -> Any:
    """
    Runs the query against the specified Elasticsearch index.
    """
    pass

  def send_query_and_evaluate_results(self) -> None:
    """
    Sends the Elasticsearch query and processes each bucket of the query result in a separate
    function.
    """
    pass

  def create_analytics_document(self) -> dict:
    """
    Returns an Elasticsearch document which will be uploaded to the dev-analytics-* index pattern.
    """
    pass
  
  def create_bulk_delete_action(self, index: str, document_id: str) -> dict:
    """
    Creates an individual Bulk API delete action.
    """
    return {"_op_type": "delete", "_index": index, "_type": "_doc", "_id": document_id}

  def create_bulk_index_action(self, index_to_update: str, document_id: str, document: dict) -> dict:
    """
    Creates an individual Bulk API index action.
    """
    return {
      "_index": index_to_update,
      "_type": "_doc",
      "_id": document_id,
      "_source": document,
      "_op_type": "index",
    }

  def create_index(self, new_index: str) -> None:
    """
    If we do not have an index titled new_index, we must create it.
    """
    if not self.elasticsearch.indices.exists(new_index):
      self.elasticsearch.indices.create(index=new_index)

  def get_most_recent_timestamp(self) -> int:
    """
    Retrieves the timestamp of the most recent document in dev-analytics-*, as determined by
    the tsEms field.
    """
    newest_timestamp_query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {"flowId": self.flow_id},
                    },
                ],
            },
        },
        "size": 1,
        "sort": [
            {
                "max_date": {"order": "desc"},
            },
        ],
    }

    res = self.elasticsearch.search(
        index=f"{analyticsconstants.ANALYTICS_INDEX_PATTERN}-*", body=newest_timestamp_query
    )
    try:
      # Attempting to get the time of the most recent timestamp of a document in the analytics
      # index.
      latest_timestamp = parser.parse(res["hits"]["hits"][0]["_source"]["tsEms"])
    except KeyError:
      # Nothing in the analytics index for the given flow_id, so use the current time.
      latest_timestamp = datetime.now()
        
    five_mins_prior = latest_timestamp - analyticsconstants.FIVE_MINS
    return int(five_mins_prior.timestamp())

  def update_nested_key(self, dictionary: dict, key_path: list, value: dict) -> None:
    """
    Updates a dictionary at the nested key defined by key_path with value, adding
    the nested keys if they do not exist
    """
    curr_dict = dictionary
    for key in key_path:
      curr_dict = curr_dict.setdefault(key, {})

    curr_dict.update(value)

class CompositeAggregationQuery(AnalyticsQuery):
  """
  Class representing an Elasticsearch composite aggregation query.
  """

  def __init__(self, **kwargs):
      super().__init__(**kwargs)
      self.format_query()

  def create_document_id(self, metric_keys):
    """
    Creates a document identifier, which is determined by the query metric and a metric key.
    """
    document_id = f"{self.metric}"
    for key in self.metric_key:
      document_id += f"-{metric_keys[key]}"

    return document_id

  def create_analytics_document(self, bucket: dict, source: dict, max_date: datetime, min_date: datetime = None) -> dict:
    document = {
      "doc_count": bucket["doc_count"],
      "max_date": max_date,
      "min_date": min_date,
      "companyId": source["companyId"],
      "flowId": source["flowId"],
      "flowName": self.mappings["flow_name"],
      "eventMessage": self.event_message,
      "metric": self.metric,
      "metric_key": bucket["key"],
    }

    # Adding additional query-specific data to the document.
    for document_key in self.document_keys:
      document[document_key] = bucket[document_key]["value"]

    for key in self.metric_key:
      document[key] = bucket["key"][key]

    if "id" in document.keys():
      node_id = document["id"]
      node = [e for e in self.mappings["nodes"] if e["id"] == node_id]
      document["nodeName"] = node["title"]

    return document

  def run_query(self) -> Any:
    return self.elasticsearch.search(index=self.index_pattern, body=self.query)

  def format_query(self) -> None:
    """
    Ensures the query performs the composite aggregation on a search of a specific flow id for a
    specific time range.
    """
    size = {"size": self.num_composite_buckets}
    self.update_nested_key(self.query, ["aggs", "composite_buckets", "composite"], size)
    
    # Requiring a max and min aggregation for the timestamp.
    self.update_nested_key(self.query, ["aggs", "composite_buckets", "aggs", "max"], {"max": {"field": "tsEms"}})
    self.update_nested_key(self.query, ["aggs", "composite_buckets", "aggs", "min"], {"min": {"field": "tsEms"}})

    # Requiring a search on a specified flow_id.
    match_phrase = {"match_phrase": {"flowId": {"query": self.flow_id}}}
    # Defining a time range for the search.
    query_range = {
        "range": {
            "tsEms": {
                "gte": self.start_date,
                "lte": self.end_date,
                "format": "epoch_second",
            }
        }
    }

    try:
      # Adding the match phrase and query range clauses to an existing must clause
      self.query["query"]["bool"]["must"].append(match_phrase)
      self.query["query"]["bool"]["must"].append(query_range)
    except KeyError:
      # The must clause, and potentially query and bool as well, does not exist
      must = {
        "must": [match_phrase, query_range],
      }
      self.update_nested_key(self.query, ["query", "bool"], must)

  def process_composite_aggregation_data(self, query_result: dict) -> str:
    """
    Processes results from the composite aggregation query, sends data fetched from the result to
    the appropriate index using a bulk request, and prepares for further processing of composite
    query results.
    """
    buckets = query_result["aggregations"]["composite_buckets"]["buckets"]
    source = query_result["hits"]["hits"][0]["_source"]

    bulk_actions = []
    for bucket in buckets:
      # Creating the document id, which relies on the metric key defined in bucket["key"]["agg"].
      document_id = self.create_document_id(bucket["key"]).encode()
      document_id = sha256(document_id).hexdigest()
      # The document belongs in the analytics index defined by the max_date.
      max_date = parser.parse(bucket["max"]["value_as_string"]).date()
      index_to_update = f"{analyticsconstants.ANALYTICS_INDEX_PATTERN}-{max_date.strftime('%Y.%m.%d')}"

      # Creating bulk actions for deleting the document with id document_id from an analytics
      # index in the date range between min_date and max_date, if the document exists. This
      # ensures we don't have a document with a given document_id saved to multiple indices.
      min_date = parser.parse(bucket["min"]["value_as_string"]).date()
      while min_date < max_date:
        index_date = min_date.strftime("%Y.%m.%d")
        index = f"{analyticsconstants.ANALYTICS_INDEX_PATTERN}-{index_date}"

        if self.elasticsearch.exists(index, document_id):
          bulk_action = self.create_bulk_delete_action(index, document_id)
          bulk_actions.append(bulk_action)
          break

        min_date += analyticsconstants.ONE_DAY

      # If index_to_update has not yet been created, we must do so before sending it any requests.
      self.create_index(index_to_update)

      document = self.create_analytics_document(bucket, source, bucket["max"]["value_as_string"])
      bulk_action = self.create_bulk_index_action(index_to_update, document_id, document)
      bulk_actions.append(bulk_action)

    # sending the bulk request to Elasticsearch
    helpers.bulk(self.elasticsearch, bulk_actions)

    # "after_key" is the identifier of the last returned bucket and will be used to return the
    # next num_composite_buckets in the composite aggregation ordering.
    after_key = query_result["aggregations"]["composite_buckets"]["after_key"]
    return after_key

  def send_query_and_evaluate_results(self) -> None:
    # running the Elasticsearch query
    query_result = self.run_query()

    # processing and querying additional composite aggregation buckets until there are no more
    # buckets to process.
    while (
      len(query_result["aggregations"]["composite_buckets"]["buckets"])
      == self.num_composite_buckets
    ):
      query_after_key = self.process_composite_aggregation_data(query_result)
      query_composite = self.query["aggs"]["composite_buckets"]["composite"]
      query_composite["after"] = query_after_key

      query_result = self.run_query()
    # processing the last set of composite aggregation buckets, if there are any to process.
    if query_result["aggregations"]["composite_buckets"]["buckets"]:
      self.process_composite_aggregation_data(query_result)

class ScanQuery(AnalyticsQuery):
  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self.format_query()

  def run_query(self) -> Any:
    return helpers.scan(self.elasticsearch, index = self.index_pattern, query = self.query)

  def create_document_id(self, hit):
    """
    Creates a document identifier, which is determined by the query metric and a metric key.
    """
    document_id = f"{self.metric}"
    for key in self.metric_key:
      try:
        document_id += f"-{hit[key]}"
      except KeyError:
        document_id += f"-{hit['_source'][key]}"

    return document_id

  def format_query(self):
    match_flow_id = {
      "match_phrase": {
        "flowId": self.flow_id
      }
    }

    query_range = {
        "range": {
            "tsEms": {
                "gte": self.start_date,
                "lte": self.end_date,
                "format": "epoch_second",
            }
        }
    }

    try:
      # Attempting to add the flow id filter to an existing must clause
      self.query["query"]["bool"]["must"].append(match_flow_id)
      self.query["query"]["bool"]["must"].append(query_range)
    except KeyError:
      # The must clause, and potentially query and bool as well, does not exist
      must = {
          "must": [match_flow_id, query_range],
      }
      self.update_nested_key(self.query, ["query", "bool"], must)

  def build_metric_key(self, source):
    """
    Builds the metric_key field for an Elasticsearch analytics document.
    """
    metric_key = {}
    for key in self.metric_key:
      metric_key[key] = source[key]
    
    return metric_key

  def create_analytics_document(self, source) -> dict:
    document  = {
      "companyId": source["companyId"],
      "doc_count": 1,
      "eventMessage": self.event_message,
      "flowId": self.flow_id,
      "flowName": self.mappings["flow_name"],
      "max_date": parser.parse(source["tsEms"]),
      "metric": self.metric,
      "metric_key": self.build_metric_key(source),
    }

    # Adding query specific fields and data to the document.
    for document_key in self.document_keys:
      if isinstance(document_key, dict):
        property = document_key["property"]
        document[property] = source["properties"][property]["value"]
      else:
        document[document_key] = source[document_key]
    
    if "id" in document.keys():
      node_id = document["id"]
      node = [e for e in self.mappings["nodes"] if e["id"] == node_id]
      document["nodeName"] = node["title"]

    return document

  def send_query_and_evaluate_results(self) -> None:
    query_result = self.run_query()
    bulk_actions = []

    # Scans return all hits that satisfy the query conditions
    for hit in query_result:
      source = hit["_source"]
      # Creating the document id using sha256 hashing
      document_id = self.create_document_id(hit).encode()
      document_id = sha256(document_id).hexdigest()

      document = self.create_analytics_document(source)
      
      # Determining the appropriate index to upload the document to and creating that index if it
      # does not exist.
      date = parser.parse(source["tsEms"]).date().strftime("%Y.%m.%d")
      index_to_update = f"{analyticsconstants.ANALYTICS_INDEX_PATTERN}-{date}"
      self.create_index(index_to_update)

      # Creating the bulk index action for the document and adding it to the list of bulk actions
      # that are sent
      bulk_action = self.create_bulk_index_action(index_to_update, document_id, document)
      #bulk_action = self.create_bulk_delete_action(index_to_update, document_id)
      bulk_actions.append(bulk_action)
    # sending the bulk request to Elasticsearch
    helpers.bulk(self.elasticsearch, bulk_actions)
