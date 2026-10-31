import re
import xml.etree.ElementTree as ET


RESULT = re.compile(r"^--- (PASS|FAIL|SKIP): (Test\S+) \(([0-9.]+)s\)$", re.MULTILINE)


def go_results(stdout, returncode, expected):
    observed = {name: {"name": name, "status": status, "seconds": float(seconds)}
                for status, name, seconds in RESULT.findall(stdout)}
    results = []
    for name in expected:
        results.append(observed.get(name, {"name": name, "status": "MISSING", "seconds": 0.0}))
    ok = returncode == 0 and all(item["status"] == "PASS" for item in results)
    return {"passed": ok, "exit_code": returncode, "expected_count": len(expected),
            "observed_count": len(observed), "tests": results}


def junit_xml(report):
    failures = sum(item["status"] in ("FAIL", "MISSING") for item in report["tests"])
    skipped = sum(item["status"] == "SKIP" for item in report["tests"])
    process_failure = report["exit_code"] != 0 and not failures
    suite = ET.Element("testsuite", name="ReserveFlow.actual-go-tests",
                       tests=str(len(report["tests"]) + int(process_failure)),
                       failures=str(failures + int(process_failure)), skipped=str(skipped))
    for item in report["tests"]:
        case = ET.SubElement(suite, "testcase", classname="reserveflow.internal.api",
                             name=item["name"], time=str(item["seconds"]))
        if item["status"] in ("FAIL", "MISSING"):
            ET.SubElement(case, "failure", message="Actual Go result: " + item["status"])
        elif item["status"] == "SKIP":
            ET.SubElement(case, "skipped", message="Actual Go test skipped; gate rejects skips")
    if process_failure:
        case = ET.SubElement(suite, "testcase", classname="harness", name="test_process_exit")
        ET.SubElement(case, "failure", message="Actual test process exited nonzero")
    return ET.tostring(suite, encoding="unicode", xml_declaration=True) + "\n"
