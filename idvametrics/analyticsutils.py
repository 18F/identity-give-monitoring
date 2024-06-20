"""
Provides utility functions for use in analytics scripting.
"""

import sys
import datetime
import dateutil.parser
import requests
import login


def epoch_time(
    date: str = None, time_delta: datetime.timedelta = datetime.timedelta(0)
) -> int:
    """
    Obtains the epoch time of a given date.
    """
    return int((dateutil.parser.parse(date) - time_delta).timestamp())


def create_bulk_delete_action(index: str, document_id: str) -> dict:
    """
    Creates an individual Bulk API delete action.
    """
    return {
        "_op_type": "delete",
        "_index": index,
        "_type": "_doc",
        "_id": document_id,
    }


def create_bulk_index_action(
    index_to_update: str, document_id: str, document: dict
) -> dict:
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


def get_authorization_header_to_idva_flows(
    email: str, password: str, login_url: str
) -> dict:
    """
    Returns a header, containing an access token, for an http request to flow data.
    """
    # the required authentication to obtain an access token
    auth = {"email": email, "password": password}

    # the required access token for accessing flow data
    json = requests.post(login_url, data=auth).json()

    try:
        access_token = json["access_token"]
        return {"Authorization": f"Bearer {access_token}"}
    except KeyError:
        print(json)
        sys.exit(1)


def get_composite_after_key(query_result: dict) -> dict:
    """
    Obtains the after_key, which is the identifier of the last returned bucket in a composite
    query result. The after_key will be used to retrieve the next num_composite_buckets in the
    composite aggregation ordering.
    """
    return query_result["aggregations"]["composite_buckets"]["after_key"]


def get_flows_by_rps(email: str, password: str, base_url: str, totp: str) -> dict:
    """
    Returns a mapping of RPs to a list of their flows, as well as whether those flows
    are enabled by a flow policy.
    """
    apps_url = f"{base_url}/v1/apps"
    auth_header = login.get_login(email, password, base_url, totp)
    json = requests.get(apps_url, headers=auth_header).json()
    try:
        apps = json["apps"]
    except KeyError:
        print(json)
        sys.exit(1)

    rps_flows = {}

    for app in apps:
        rp = app["metadata"]["rpName"]
        flows = []
        for policy in app["policies"]:
            status = policy["status"]
            for flow in policy["flows"]:
                flow_id = flow["flowId"]
                flows.append({"flow": flow_id, "status": status})
        if rp in rps_flows:
            rps_flows[rp]["flows"].extend(flows)
        else:
            rps_flows[rp] = {"flows": flows}

    return rps_flows


def get_mappings(
    flow_id: str, email: str, password: str, base_url: str, totp: str
) -> dict:
    """
    Returns the mappings of flow id to flow name and node id to node names.
    """
    auth_header = login.get_login(email, password, base_url, totp)

    # pulling out the flow data for a flow of a given flow id
    flow_url = f"{base_url}/v1/flows/{flow_id}"
    json = requests.get(flow_url, headers=auth_header).json()
    try:
        flow = json["flowInfo"]
    except KeyError:
        print(json)
        sys.exit(1)
    # We always run the script with one specified flow id, so flows should always have one element
    nodes = flow["graphData"]["elements"]["nodes"]

    node_mappings = []
    for node in nodes:
        try:
            # the node title is defined
            node_title = node["data"]["properties"]["nodeTitle"]["value"]
        except KeyError:
            # the node title has not yet been defined
            node_title = None

        try:
            # the node description is defined
            node_description = node["data"]["properties"]["nodeDescription"]
        except KeyError:
            # the node description has not yet been defined
            node_description = None

        node_mappings.append(
            {
                "id": node["data"]["id"],
                "title": node_title,
                "description": node_description,
            }
        )
    ids_names_mapping = {
        "flow_id": flow_id,
        "flow_name": flow["name"],
        "nodes": node_mappings,
        "company_id": flow["companyId"],
    }
    return ids_names_mapping


def update_nested_key(dictionary: dict, key_path: list, value: dict) -> None:
    """
    Updates a dictionary at the nested key defined by key_path with value, adding
    the nested keys if they do not exist
    """
    curr_dict = dictionary
    for key in key_path:
        curr_dict = curr_dict.setdefault(key, {})

    curr_dict.update(value)
