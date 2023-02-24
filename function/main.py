import requests
import google.cloud.dlp
import json
import base64
import os
from google.cloud import secretmanager

PROJECT_ID = os.environ.get('PROJECT_ID')
PAGERDUTY_SERVICE_ID = os.environ.get('PAGERDUTY_SERVICE_ID')

def get_secret(project, secret_id, version_id):
    secret_client = secretmanager.SecretManagerServiceClient()
    secret_name = f'projects/{project}/secrets/{secret_id}/versions/{version_id}'
    response = secret_client.access_secret_version(request={"name": secret_name})
    payload = response.payload.data.decode("UTF-8")
    return payload

def send_to_pagerduty(project, content):
    print('Sending to PagerDuty')
    url = 'https://events.pagerduty.com/generic/2010-04-15/create_event.json'

    pagerduty_token = get_secret(project, 'pagerduty_token', 'latest')

    headers = {"Authorization": "Token token={}".format(pagerduty_token)}
    content = content.replace("\'", "\"")
    content = content.replace("None", "\"None\"")

    data = {
    "service_key": PAGERDUTY_SERVICE_ID,
    "event_type": "trigger",
    "description": "Admin Grant Alert",
    "client": "Google Cloud Operations Alert",
    "details": json.loads(content)
    }

    response = requests.post(url, json=data, headers=headers)

    print("Status Code", response.status_code)
    print("JSON Response ", response.json())

def deidentify_with_replace_infotype(project, input_str, info_types):
    # Instantiate a client
    dlp = google.cloud.dlp_v2.DlpServiceClient()

    # Convert the project id into a full resource id.
    parent = f"projects/{project}"

    # Construct inspect configuration dictionary
    inspect_config = {"info_types": info_types}

    # Construct deidentify configuration dictionary
    deidentify_config = {
        "info_type_transformations": {
            "transformations": [
                {"primitive_transformation": {"replace_with_info_type_config": {}}}
            ]
        }
    }

    # Call the API
    response = dlp.deidentify_content(
        request={
            "parent": parent,
            "deidentify_config": deidentify_config,
            "inspect_config": inspect_config,
            "item": {"value": input_str},
        }
    )

    print("Masked With InfoType Data")
    send_to_pagerduty(project, response.item.value)

def check_content(project, content):
     dlp_client = google.cloud.dlp_v2.DlpServiceClient()

     item = {"value": content}

     info_types = [{"name": "FIRST_NAME"}, {"name": "LAST_NAME"}, {"name": "EMAIL_ADDRESS"}]

     min_likelihood = google.cloud.dlp_v2.Likelihood.LIKELIHOOD_UNSPECIFIED

     max_findings = 0

     include_quote = True

     inspect_config = {
          "info_types": info_types,
          "min_likelihood": min_likelihood,
          "include_quote": include_quote,
          "limits": {"max_findings_per_request": max_findings},
     }
     parent = f"projects/{project}"

     response = dlp_client.inspect_content(
          request={"parent": parent, "inspect_config": inspect_config, "item": item}
     )

     if response.result.findings:
          for finding in response.result.findings:
               try:
                    print("Value found: {}".format(finding.quote))
               except AttributeError:
                    pass
               print("Info type: {}".format(finding.info_type.name))
               likelihood = finding.likelihood.name
               print("Likelihood: {}".format(likelihood))
               print("Not Sending to PagerDuty, PII Found")
          deidentify_with_replace_infotype(project, content, info_types)
     else:
          print("No findings.")
          send_to_pagerduty(content)
          
def entry(event=None, context=None):
    content = base64.b64decode(event['data']).decode('utf-8')
    content_dict = json.loads(content)
    content_dict['incident']['condition']['conditionMatchedLog']['filter'] = "[REDACTED]"
    check_content(PROJECT_ID, str(content_dict))