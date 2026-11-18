"""Pruebas unitarias de seguridad para la herramienta de inyección de fallas."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fenix.utils.errors import PermanentError, RetryableError, ValidationError
from tests.demo.inject_fault import inject_fault
from tests.demo.notify_stub import NotifyStub


GROUP = "grupo01"
EXPECTED = {
    "ManagedBy": "ppa2",
    "Project": "fenix",
    "GroupId": GROUP,
    "Owner": GROUP,
}


def _write_inventory(path: Path, alias: str, resource_type: str, resource_id: str) -> None:
    path.write_text(
        json.dumps({alias: {
            "type": resource_type,
            "id": resource_id,
            "expected_tags": EXPECTED,
        }}),
        encoding="utf-8",
    )


class FakeEC2:
    def __init__(self, group_id: str = GROUP, state: str = "running") -> None:
        self.state = state
        self.stop_calls: list[list[str]] = []
        self.instance = {
            "InstanceId": "i-00000000000000001",
            "State": {"Name": state},
            "Tags": [{"Key": key, "Value": value} for key, value in {
                **EXPECTED, "GroupId": group_id,
            }.items()],
        }

    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, Any]:
        assert InstanceIds == [self.instance["InstanceId"]]
        self.instance["State"]["Name"] = self.state
        return {"Reservations": [{"Instances": [self.instance]}]}

    def stop_instances(self, *, InstanceIds: list[str]) -> dict[str, Any]:
        self.stop_calls.append(InstanceIds)
        self.state = "stopped"
        return {"StoppingInstances": []}


class FakeS3:
    def __init__(self, owner: str | None = GROUP) -> None:
        tags = {**EXPECTED, "Department": "operations"}
        if owner is None:
            tags.pop("Owner")
        else:
            tags["Owner"] = owner
        self.tag_set = [{"Key": key, "Value": value} for key, value in tags.items()]
        self.put_calls: list[dict[str, Any]] = []

    def get_bucket_tagging(self, *, Bucket: str) -> dict[str, Any]:
        assert Bucket == "fenix-test-bucket"
        return {"TagSet": list(self.tag_set)}

    def put_bucket_tagging(self, *, Bucket: str, Tagging: dict[str, Any]) -> None:
        assert Bucket == "fenix-test-bucket"
        self.put_calls.append(Tagging)
        self.tag_set = list(Tagging["TagSet"])


def test_inject_fault_stops_only_inventory_ec2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUP_ID", GROUP)
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, "node-01", "ec2", "i-00000000000000001")
    ec2 = FakeEC2()

    result = inject_fault("node-01", inventory_path=inventory,
                          client_factory=lambda service: ec2 if service == "ec2" else None)

    assert result["status"] == "injected"
    assert ec2.stop_calls == [["i-00000000000000001"]]


def test_inject_fault_is_idempotent_for_already_stopped_ec2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROUP_ID", GROUP)
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, "node-01", "ec2", "i-00000000000000001")
    ec2 = FakeEC2(state="stopped")

    result = inject_fault("node-01", inventory_path=inventory,
                          client_factory=lambda service: ec2 if service == "ec2" else None)

    assert result["status"] == "already_injected"
    assert ec2.stop_calls == []


def test_inject_fault_refuses_ec2_with_other_group_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROUP_ID", GROUP)
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, "node-01", "ec2", "i-00000000000000001")
    ec2 = FakeEC2(group_id="otro-grupo")

    with pytest.raises(ValidationError):
        inject_fault("node-01", inventory_path=inventory,
                     client_factory=lambda service: ec2 if service == "ec2" else None)
    assert ec2.stop_calls == []


def test_inject_fault_removes_only_owner_and_preserves_other_s3_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROUP_ID", GROUP)
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, "bucket-01", "s3", "fenix-test-bucket")
    s3 = FakeS3()

    result = inject_fault("bucket-01", inventory_path=inventory,
                          client_factory=lambda service: s3 if service == "s3" else None)

    final_tags = {item["Key"]: item["Value"] for item in s3.tag_set}
    assert result["status"] == "injected"
    assert "Owner" not in final_tags
    assert final_tags["Department"] == "operations"
    assert final_tags["GroupId"] == GROUP
    assert len(s3.put_calls) == 1


def test_inject_fault_does_not_repeat_s3_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUP_ID", GROUP)
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, "bucket-01", "s3", "fenix-test-bucket")
    s3 = FakeS3(owner=None)

    result = inject_fault("bucket-01", inventory_path=inventory,
                          client_factory=lambda service: s3 if service == "s3" else None)

    assert result["status"] == "already_injected"
    assert s3.put_calls == []


def test_inject_fault_rejects_alias_not_in_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROUP_ID", GROUP)
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, "node-01", "ec2", "i-00000000000000001")

    with pytest.raises(ValidationError):
        inject_fault("node-foreign", inventory_path=inventory,
                     client_factory=lambda service: None)


def test_notify_stub_simulates_429_then_success() -> None:
    notify = NotifyStub(["429", "ok"])
    with pytest.raises(RetryableError):
        notify({"event_id": "evt-test"})
    result = notify({"event_id": "evt-test"})
    assert result["ok"] is True
    assert notify.calls == 2


def test_notify_stub_simulates_permanent_failure_without_network() -> None:
    notify = NotifyStub(["permanent"])
    with pytest.raises(PermanentError):
        notify({"event_id": "evt-test"})
    assert notify.calls == 1
