"""
This file is for analytics scripting, querying data from the skevents-* and eventsoutcome-*
index patterns and placing the result in the analytics-* index pattern for further
visualizations.
"""

import argparse
import analyticsquery
import analyticsutils
import queries


EVENTS_INDEX_PATTERN = "dev-eventsoutcome-*"
SK_INDEX_PATTERN = "dev-skevents-*"
METRIC_DEFINITIONS = {
    "connector_pass_rate": {
        "index_pattern": EVENTS_INDEX_PATTERN,
        "metric": "connector_pass_rate",
        "metric_keys": ["flowId", "interactionId", "id", "tsEms"],
        "document_keys": [
            "id",
            {"property": "outcomeStatus"},
        ],
    },
    "connector_response_time": {
        "index_pattern": SK_INDEX_PATTERN,
        "metric": "connector_response_time",
        "metric_keys": ["interactionId", "id", "tsEms"],
        "document_keys": ["executionTime", "id"],
        "top_hit_fields": [],
    },
    "interaction_response_time": {
        "index_pattern": SK_INDEX_PATTERN,
        "metric": "interaction_response_time",
        "metric_keys": ["interactionId"],
        "document_keys": ["sessionLength"],
    },
    "drop_off": {
        "index_pattern": SK_INDEX_PATTERN,
        "metric": "drop_off",
        "metric_keys": ["interactionId"],
        "document_keys": [],
        "top_hit_fields": ["id"],
    },
}


def get_command_line_arguments():
    """
    Returns command line argument names and values.
    """
    cmd_line_parser = argparse.ArgumentParser()
    cmd_line_parser.add_argument("--host")
    cmd_line_parser.add_argument("--port")
    cmd_line_parser.add_argument("--flow_id")

    cmd_line_parser.add_argument("--start_date", default=None)
    cmd_line_parser.add_argument("--end_date", default=None)
    cmd_line_parser.add_argument("--username")
    cmd_line_parser.add_argument("--password")
    cmd_line_parser.add_argument("--base_url")
    cmd_line_parser.add_argument("--totp", default=None)
    cmd_line_parser.add_argument("--env", default="dev")
    arguments = cmd_line_parser.parse_args()

    return arguments


def main() -> None:
    """
    The main method for running the script.
    """

    arguments = get_command_line_arguments()

    mappings = analyticsutils.get_mappings(
        arguments.flow_id,
        arguments.username,
        arguments.password,
        arguments.base_url,
        arguments.totp,
    )

    rps_flows = analyticsutils.get_flows_by_rps(
        arguments.username,
        arguments.password,
        arguments.base_url,
        arguments.totp,
    )

    connector_pass_rate = analyticsquery.ScanQuery(
        queries.connector_pass_rate,
        METRIC_DEFINITIONS["connector_pass_rate"],
        mappings,
        arguments,
    )
    connector_pass_rate.run()

    connector_response_time = analyticsquery.ScanQuery(
        queries.connector_response_time,
        METRIC_DEFINITIONS["connector_response_time"],
        mappings,
        arguments,
    )
    connector_response_time.run()

    workflow_response_time = analyticsquery.CompositeAggregationQuery(
        queries.workflow_response_time,
        METRIC_DEFINITIONS["interaction_response_time"],
        mappings,
        arguments,
    )
    workflow_response_time.run()

    drop_off = analyticsquery.CompositeAggregationQuery(
        queries.drop_off, METRIC_DEFINITIONS["drop_off"], mappings, arguments
    )
    drop_off.run()


if __name__ == "__main__":
    main()
