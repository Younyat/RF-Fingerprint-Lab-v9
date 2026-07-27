"""Physical Device Registry contracts.

Hard rule enforced structurally here, not just documented: physical_unit_id
never appears anywhere near a BLE address in this file. A BLE address is
evidence that MAY be bound to a unit (AddressBinding, N addresses : 0-or-1
unit), never an identity by itself. An unseen address never creates a unit --
there is no constructor path in this module that derives physical_unit_id
from anything address-shaped.
"""
from __future__ import annotations

from typing import Literal

from .common import StudioContract, identity_hash
from .evidence import LabelEvidenceItem

PHYSICAL_UNIT_SCHEMA_VERSION = "ble-rffi-studio-physical-unit-v1"
ADDRESS_BINDING_SCHEMA_VERSION = "ble-rffi-studio-address-binding-v1"

PhysicalUnitStatus = Literal["ACTIVE", "RETIRED", "SUSPECTED_ADDRESS_CHANGE"]
BindingStatus = Literal["BOUND", "UNBOUND", "CONFLICTING"]


class PhysicalUnitRecord(StudioContract):
    schema_version: Literal["ble-rffi-studio-physical-unit-v1"] = PHYSICAL_UNIT_SCHEMA_VERSION
    physical_unit_id: str  # operator-declared, e.g. "CC2650-UNIT-01" -- never derived
    project_id: str
    device_family: str
    manufacturer: str | None = None
    model: str | None = None
    internal_serial: str | None = None
    status: PhysicalUnitStatus = "ACTIVE"
    operator_declaration_id: str
    first_registered_at: str


class AddressBindingHistoryItem(StudioContract):
    previous_physical_unit_id: str | None
    changed_at: str
    reason: str


class AddressBinding(StudioContract):
    """address -> at most one physical_unit_id, with an evidence trail and a
    full history of reassignment. One unit MAY have many bindings (multiple
    addresses observed over time, e.g. random address rotation); this model
    never enforces the reverse direction."""

    schema_version: Literal["ble-rffi-studio-address-binding-v1"] = ADDRESS_BINDING_SCHEMA_VERSION
    binding_id: str
    project_id: str
    address: str
    address_type: str
    bound_physical_unit_id: str | None = None
    binding_status: BindingStatus
    binding_evidence: list[LabelEvidenceItem] = []
    first_seen: str
    last_seen: str
    history: list[AddressBindingHistoryItem] = []

    @staticmethod
    def make_binding_id(project_id: str, address: str, address_type: str) -> str:
        return identity_hash(project_id, address.upper(), address_type, prefix="bind")
