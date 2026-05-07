import subprocess

import config


TESTCASE_NODE_TYPE_ID = 3
TEXTAREA_CUSTOM_FIELD_TYPE = 20


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def _sql_string(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def _run_mysql(sql: str) -> str:
    command = [
        config.MYSQL_EXE,
        f"-h{config.TESTLINK_DB_HOST}",
        f"-u{config.TESTLINK_DB_USER}",
        f"-p{config.TESTLINK_DB_PASSWORD}",
        "--batch",
        "--raw",
        "--skip-column-names",
        config.TESTLINK_DB_NAME,
        "-e",
        sql,
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def ensure_automation_testdata_custom_field() -> int:
    if not config.PROJECT_ID:
        raise ValueError("TESTLINK_PROJECT_ID or PROJECT_ID is required to assign the custom field.")

    field_name = _sql_string(config.TESTLINK_CUSTOM_FIELD_NAME)
    field_label = _sql_string(config.TESTLINK_CUSTOM_FIELD_LABEL)

    sql = f"""
INSERT INTO custom_fields
    (name, label, type, possible_values, default_value, valid_regexp,
     length_min, length_max, show_on_design, enable_on_design,
     show_on_execution, enable_on_execution,
     show_on_testplan_design, enable_on_testplan_design)
SELECT
    {field_name}, {field_label}, {TEXTAREA_CUSTOM_FIELD_TYPE}, '', '', '',
    0, 4000, 1, 1, 0, 0, 0, 0
WHERE NOT EXISTS (
    SELECT 1 FROM custom_fields WHERE name = {field_name}
);

SET @automation_field_id := (
    SELECT id FROM custom_fields WHERE name = {field_name} LIMIT 1
);

INSERT IGNORE INTO cfield_node_types (field_id, node_type_id)
VALUES (@automation_field_id, {TESTCASE_NODE_TYPE_ID});

INSERT IGNORE INTO cfield_testprojects
    (field_id, testproject_id, display_order, location, active, required,
     required_on_design, required_on_execution, monitorable)
VALUES
    (@automation_field_id, {config.PROJECT_ID}, 1, 1, 1, 0, 0, 0, 0);

SELECT @automation_field_id;
"""
    log_info("Ensuring TestLink automation test data custom field exists and is assigned.")
    output = _run_mysql(sql)
    field_id = int(output.splitlines()[-1])
    log_success(
        f"TestLink custom field ready: {config.TESTLINK_CUSTOM_FIELD_NAME} (id {field_id})."
    )
    return field_id


def upsert_testcase_custom_field_value(field_id: int, testcase_version_id: int, value: str) -> None:
    sql = f"""
INSERT INTO cfield_design_values (field_id, node_id, value)
VALUES ({int(field_id)}, {int(testcase_version_id)}, {_sql_string(value)})
ON DUPLICATE KEY UPDATE value = VALUES(value);
"""
    _run_mysql(sql)
