"""Configure the lab's SCM pipeline job and connect its dedicated inbound agent."""
from __future__ import annotations

import argparse
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET

from lab_config import ROOT, JOB, JenkinsClient, assert_no_secrets, configuration, private_write

ACTIONS = ("DEPLOY_GOOD", "DEPLOY_UNHEALTHY", "ROLLBACK", "DEPLOY_POSTCHECK_FAIL")


def job_xml(values: dict[str, str]) -> bytes:
    reference = values["LAB_GIT_REF"]
    if reference != "main" and not re.fullmatch(r"[a-f0-9]{40}", reference):
        raise ValueError("Invalid source reference")
    definition = ET.Element("flow-definition", {"plugin": "workflow-job"})
    ET.SubElement(definition, "description").text = "Local ReserveFlow deployment lab. Jenkinsfile is loaded from the versioned lab repository."
    ET.SubElement(definition, "keepDependencies").text = "false"
    properties = ET.SubElement(definition, "properties")
    parameters = ET.SubElement(ET.SubElement(properties, "hudson.model.ParametersDefinitionProperty"), "parameterDefinitions")
    choice = ET.SubElement(parameters, "hudson.model.ChoiceParameterDefinition")
    ET.SubElement(choice, "name").text = "ACTION"
    ET.SubElement(choice, "description").text = "Synthetic lab scenario; expected failures are intentional verification cases."
    choices = ET.SubElement(ET.SubElement(choice, "choices", {"class": "java.util.Arrays$ArrayList"}), "a", {"class": "string-array"})
    for action in ACTIONS:
        ET.SubElement(choices, "string").text = action
    flow = ET.SubElement(definition, "definition", {"class": "org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition", "plugin": "workflow-cps"})
    scm = ET.SubElement(flow, "scm", {"class": "hudson.plugins.git.GitSCM", "plugin": "git"})
    ET.SubElement(scm, "configVersion").text = "2"
    remote = ET.SubElement(ET.SubElement(scm, "userRemoteConfigs"), "hudson.plugins.git.UserRemoteConfig")
    ET.SubElement(remote, "url").text = values["LAB_GIT_URL"]
    branch = ET.SubElement(ET.SubElement(scm, "branches"), "hudson.plugins.git.BranchSpec")
    ET.SubElement(branch, "name").text = "*/main" if reference == "main" else reference
    ET.SubElement(scm, "doGenerateSubmoduleConfigurations").text = "false"
    ET.SubElement(scm, "submoduleCfg", {"class": "empty-list"})
    ET.SubElement(scm, "extensions")
    ET.SubElement(flow, "scriptPath").text = "Jenkinsfile"
    ET.SubElement(flow, "lightweight").text = "true"
    ET.SubElement(definition, "triggers")
    ET.SubElement(definition, "disabled").text = "false"
    return ET.tostring(definition, encoding="utf-8", xml_declaration=True)


def bootstrap(timeout: int, wait_agent: bool) -> dict:
    values = configuration()
    client = JenkinsClient(values)
    status = client.ready(timeout)
    if status["numExecutors"] != 0:
        raise RuntimeError("The controller must have zero build executors")
    if wait_agent:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            node = client.json("/computer/builder/api/json?tree=offline,temporarilyOffline,numExecutors")
            if not node["offline"] and not node["temporarilyOffline"]:
                if node["numExecutors"] != 1:
                    raise RuntimeError("The lab agent must have exactly one executor")
                return {"result": "PASS", "agent": "builder", "executors": 1, "online": True}
            time.sleep(2)
        raise RuntimeError("The dedicated agent did not connect within the timeout")
    raw, _ = client.request("/computer/builder/jenkins-agent.jnlp")
    arguments = ET.fromstring(raw).findall(".//argument")
    if not arguments or not arguments[0].text or not re.fullmatch(r"[a-f0-9]{64}", arguments[0].text):
        raise RuntimeError("Controller did not return a valid dedicated agent secret")
    private_write(ROOT / ".local/agent.env", "JENKINS_SECRET=" + arguments[0].text + "\n")
    boundary = 'jenkins-lab-' + uuid.uuid4().hex
    source = (ROOT / 'Jenkinsfile').read_bytes()
    multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="jenkinsfile"; filename="Jenkinsfile"\r\nContent-Type: text/plain\r\n\r\n'.encode() + source + f'\r\n--{boundary}--\r\n'.encode())
    validation, _ = client.request('/pipeline-model-converter/validate', multipart, 'multipart/form-data; boundary=' + boundary)
    if 'successfully validated' not in validation.decode('utf-8').lower():
        assert_no_secrets(validation, values)
        raise RuntimeError('The actual Jenkins declarative validator rejected Jenkinsfile: ' + validation.decode('utf-8')[:1500])
    existing = {job["name"] for job in status["jobs"]}
    path = f"/job/{JOB}/config.xml" if JOB in existing else f"/createItem?name={JOB}"
    client.request(path, job_xml(values), "application/xml")
    return {"result": "PASS", "job": JOB, "agent_secret": "initialized privately", "git_ref": values["LAB_GIT_REF"], 'jenkinsfile_validator': 'PASS'}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--wait-agent", action="store_true")
    args = parser.parse_args()
    print(json.dumps(bootstrap(args.timeout, args.wait_agent)))
