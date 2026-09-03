"""Quirk for Aqara aqara.feeder.acn001."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import string
from typing import Any, Final

from zigpy import types
from zigpy.zcl import AttributeReportedEvent, AttributeUpdatedEvent, foundation
from zigpy.zcl.clusters.general import UTC, ZIGBEE_EPOCH, OnOff, Time
from zigpy.zcl.foundation import BaseAttributeDefs, ZCLAttributeDef

from zhaquirks import EventableCluster, LocalDataCluster
from zhaquirks.builder import (
    BinarySensorDeviceClass,
    EntityPlatform,
    EntityType,
    QuirkBuilder,
    SensorStateClass,
    UnitOfMass,
)
from zhaquirks.const import (
    ATTRIBUTE_ID,
    ATTRIBUTE_NAME,
    COMMAND_ATTRIBUTE_UPDATED,
    UNKNOWN,
    VALUE,
    ZHA_SEND_EVENT,
)
from zhaquirks.xiaomi import XiaomiAqaraE1Cluster

# 32 bit signed integer values that are encoded in FEEDER_ATTR = 0xFFF1
FEEDING = 0x04150055
FEEDING_REPORT = 0x041502BC
PORTIONS_DISPENSED = 0x0D680055
WEIGHT_DISPENSED = 0x0D690055
ERROR_DETECTED = 0x0D0B0055
SCHEDULING_STRING = 0x080008C8
DISABLE_LED_INDICATOR = 0x04170055
CHILD_LOCK = 0x04160055
FEEDING_MODE = 0x04180055
SERVING_SIZE = 0x0E5C0055
PORTION_WEIGHT = 0x0E5F0055
BATTERY_MODE = 0x0D090055

FEEDER_ATTR = 0xFFF1
FEEDER_ATTR_NAME = "feeder_attr"

FEEDER_ATTR_TYPE_ID = 0x41

MAX_SCHEDULE_ENTRIES = 5

DAYS_MAP = {
    "everyday": 0x7F,
    "workdays": 0x1F,
    "weekend": 0x60,
    "mon": 0x01,
    "tue": 0x02,
    "wed": 0x04,
    "thu": 0x08,
    "fri": 0x10,
    "sat": 0x20,
    "sun": 0x40,
    "m-w-f-s": 0x55,
    "t-t-s": 0x2A,
}


DAYS_REVERSE_MAP = {v: k for k, v in DAYS_MAP.items()}

# Fake ZCL attribute ids we can use for entities for the opple cluster
ZCL_FEEDING = 0x1388
ZCL_LAST_FEEDING_SOURCE = 0x1389
ZCL_LAST_FEEDING_SIZE = 0x138A
ZCL_PORTIONS_DISPENSED = 0x138B
ZCL_WEIGHT_DISPENSED = 0x138C
ZCL_ERROR_DETECTED = 0x138D
ZCL_DISABLE_LED_INDICATOR = 0x138E
ZCL_CHILD_LOCK = 0x138F
ZCL_FEEDING_MODE = 0x1390
ZCL_SERVING_SIZE = 0x1391
ZCL_PORTION_WEIGHT = 0x1392
ZCL_SCHEDULE = 0x1393
ZCL_BATTERY_MODE = 0x1394

AQARA_TO_ZCL: dict[int, int] = {
    FEEDING: ZCL_FEEDING,
    ERROR_DETECTED: ZCL_ERROR_DETECTED,
    DISABLE_LED_INDICATOR: ZCL_DISABLE_LED_INDICATOR,
    CHILD_LOCK: ZCL_CHILD_LOCK,
    FEEDING_MODE: ZCL_FEEDING_MODE,
    SERVING_SIZE: ZCL_SERVING_SIZE,
    PORTION_WEIGHT: ZCL_PORTION_WEIGHT,
    BATTERY_MODE: ZCL_BATTERY_MODE,
}

ZCL_TO_AQARA: dict[int, int] = {
    ZCL_FEEDING: FEEDING,
    ZCL_DISABLE_LED_INDICATOR: DISABLE_LED_INDICATOR,
    ZCL_CHILD_LOCK: CHILD_LOCK,
    ZCL_FEEDING_MODE: FEEDING_MODE,
    ZCL_SERVING_SIZE: SERVING_SIZE,
    ZCL_PORTION_WEIGHT: PORTION_WEIGHT,
    ZCL_ERROR_DETECTED: ERROR_DETECTED,
    ZCL_SCHEDULE: SCHEDULING_STRING,
    ZCL_BATTERY_MODE: BATTERY_MODE,
}

LOGGER = logging.getLogger(__name__)


class FeederTimeCluster(LocalDataCluster, Time):
    """Use local time instead of UTC.

    The feeder polls the time cluster during interview and expects the
    value returned in the time attribute to already be adjusted to the
    user's local timezone. This benefits the onboard schedule, as well
    as the weight and portions distributed per day, and the LED indicator.

    Note: ZCL defines the `time` attribute as UTC; this deliberately
    returns local time instead because that's what the feeder firmware
    expects (it does not honor `time_zone`/`local_time`).
    """

    def handle_read_attribute_time(self) -> types.UTCTime:
        """Return local-adjusted time value for the *time* attribute."""
        now = datetime.now(UTC)
        tz_offset = datetime.now().astimezone().utcoffset()
        assert tz_offset is not None
        return types.UTCTime((now + tz_offset - ZIGBEE_EPOCH).total_seconds())


class FeedingSource(types.enum8):
    """Feeding source.

    Schedule = onboard schedule,
    Feeder = feed button on feeder,
    HomeAssistant = feed button (including automations) in HA
    """

    Schedule = 0x00
    Feeder = 0x01
    HomeAssistant = 0x02


class FeedingMode(types.enum8):
    """Feeding mode."""

    Manual = 0x00
    Schedule = 0x01


class OppleCluster(XiaomiAqaraE1Cluster, EventableCluster):
    """Opple cluster."""

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        feeding: Final = ZCLAttributeDef(
            id=ZCL_FEEDING, type=types.Bool, manufacturer_code=0x115F
        )
        last_feeding_source: Final = ZCLAttributeDef(
            id=ZCL_LAST_FEEDING_SOURCE, type=FeedingSource, manufacturer_code=0x115F
        )
        last_feeding_size: Final = ZCLAttributeDef(
            id=ZCL_LAST_FEEDING_SIZE, type=types.uint8_t, manufacturer_code=0x115F
        )
        portions_dispensed: Final = ZCLAttributeDef(
            id=ZCL_PORTIONS_DISPENSED, type=types.uint16_t, manufacturer_code=0x115F
        )
        weight_dispensed: Final = ZCLAttributeDef(
            id=ZCL_WEIGHT_DISPENSED, type=types.uint32_t, manufacturer_code=0x115F
        )
        error_detected: Final = ZCLAttributeDef(
            id=ZCL_ERROR_DETECTED, type=types.Bool, manufacturer_code=0x115F
        )
        disable_led_indicator: Final = ZCLAttributeDef(
            id=ZCL_DISABLE_LED_INDICATOR, type=types.Bool, manufacturer_code=0x115F
        )
        child_lock: Final = ZCLAttributeDef(
            id=ZCL_CHILD_LOCK, type=types.Bool, manufacturer_code=0x115F
        )
        feeding_mode: Final = ZCLAttributeDef(
            id=ZCL_FEEDING_MODE, type=FeedingMode, manufacturer_code=0x115F
        )
        serving_size: Final = ZCLAttributeDef(
            id=ZCL_SERVING_SIZE, type=types.uint8_t, manufacturer_code=0x115F
        )
        portion_weight: Final = ZCLAttributeDef(
            id=ZCL_PORTION_WEIGHT, type=types.uint8_t, manufacturer_code=0x115F
        )
        schedule: Final = ZCLAttributeDef(
            id=ZCL_SCHEDULE,
            type=types.CharacterString,
            manufacturer_code=0x115F,
        )
        feeder_attr: Final = ZCLAttributeDef(
            id=FEEDER_ATTR, type=types.LVBytes, manufacturer_code=0x115F
        )
        battery_mode: Final = ZCLAttributeDef(
            id=ZCL_BATTERY_MODE, type=types.Bool, manufacturer_code=0x115F
        )

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self._send_sequence: int = None

        # Set default values for attributes
        if ZCL_DISABLE_LED_INDICATOR not in self._attr_cache:
            self._update_attribute(ZCL_DISABLE_LED_INDICATOR, False)
        if ZCL_CHILD_LOCK not in self._attr_cache:
            self._update_attribute(ZCL_CHILD_LOCK, False)
        if ZCL_FEEDING_MODE not in self._attr_cache:
            self._update_attribute(ZCL_FEEDING_MODE, FeedingMode.Manual)
        if ZCL_SERVING_SIZE not in self._attr_cache:
            self._update_attribute(ZCL_SERVING_SIZE, 1)
        if ZCL_PORTION_WEIGHT not in self._attr_cache:
            self._update_attribute(ZCL_PORTION_WEIGHT, 8)
        if ZCL_ERROR_DETECTED not in self._attr_cache:
            self._update_attribute(ZCL_ERROR_DETECTED, False)
        if ZCL_PORTIONS_DISPENSED not in self._attr_cache:
            self._update_attribute(ZCL_PORTIONS_DISPENSED, 0)
        if ZCL_WEIGHT_DISPENSED not in self._attr_cache:
            self._update_attribute(ZCL_WEIGHT_DISPENSED, 0)
        if ZCL_BATTERY_MODE not in self._attr_cache:
            self._update_attribute(ZCL_BATTERY_MODE, False)
        if ZCL_SCHEDULE not in self._attr_cache:
            self._update_attribute(ZCL_SCHEDULE, "[]")

        self.on_event(AttributeUpdatedEvent.event_type, self._handle_attribute_event)

    def _handle_attribute_event(
        self, event: AttributeReportedEvent | AttributeUpdatedEvent
    ) -> None:
        """Handle attribute report/update event to parse feeder attribute."""
        if event.attribute_id != FEEDER_ATTR:
            return

        raw: bytes | None = None
        if isinstance(event.value, bytes):
            try:
                raw = bytes(event.value)
            except (TypeError, ValueError):
                raw = None

        if raw is not None:
            self._parse_feeder_attribute(raw)

    def _handle_attribute_report(
        self, event: AttributeReportedEvent | AttributeUpdatedEvent
    ) -> None:
        """Sanitize values when EventableCluster creates zha_event."""
        out_value = event.value
        if isinstance(out_value, bytes):
            try:
                out_value = out_value.hex()
            except (TypeError, ValueError):
                LOGGER.exception("Failed sanitizing event value")

        self.listener_event(
            ZHA_SEND_EVENT,
            COMMAND_ATTRIBUTE_UPDATED,
            {
                ATTRIBUTE_ID: event.attribute_id,
                ATTRIBUTE_NAME: event.attribute_name or UNKNOWN,
                VALUE: out_value,
            },
        )

    def _update_feeder_attribute(self, attrid: int, value: Any) -> None:
        zcl_attr_def = self.attributes.get(AQARA_TO_ZCL[attrid])
        self._update_attribute(zcl_attr_def.id, zcl_attr_def.type.deserialize(value)[0])

    def _parse_feeder_attribute(self, value: Any) -> None:
        """Parse the feeder attribute."""
        if isinstance(value, str):
            try:
                value = bytes.fromhex(value)
            except ValueError:
                return

        try:
            value = bytes(value)
        except (TypeError, ValueError):
            return

        if len(value) < 8:
            return

        try:
            attribute, _ = types.int32s_be.deserialize(value[3:7])
        except ValueError:
            return
        LOGGER.debug("OppleCluster._parse_feeder_attribute: attribute: %s", attribute)

        try:
            length, _ = types.uint8_t.deserialize(value[7:8])
        except ValueError:
            return
        LOGGER.debug("OppleCluster._parse_feeder_attribute: length: %s", length)

        if len(value) < 8 + length:
            return
        attribute_value = value[8 : (length + 8)]
        LOGGER.debug("OppleCluster._parse_feeder_attribute: value: %s", attribute_value)

        if attribute in AQARA_TO_ZCL:
            self._update_feeder_attribute(attribute, attribute_value)
        elif attribute == FEEDING_REPORT:
            attr_str = attribute_value.decode("utf-8")
            feeding_source = FeedingSource(int(attr_str[0:2], 16))
            feeding_size = int(attr_str[2:4], 16)
            self._update_attribute(ZCL_LAST_FEEDING_SOURCE, feeding_source)
            self._update_attribute(ZCL_LAST_FEEDING_SIZE, feeding_size)
        elif attribute == PORTIONS_DISPENSED:
            portions_per_day, _ = types.uint16_t_be.deserialize(attribute_value)
            self._update_attribute(ZCL_PORTIONS_DISPENSED, portions_per_day)
        elif attribute == WEIGHT_DISPENSED:
            weight_per_day, _ = types.uint32_t_be.deserialize(attribute_value)
            self._update_attribute(ZCL_WEIGHT_DISPENSED, weight_per_day)
        elif attribute == SCHEDULING_STRING:
            self._parse_schedule(attribute_value)
        else:
            LOGGER.debug(
                "OppleCluster._parse_feeder_attribute: unhandled attribute: %s value: %s",
                attribute,
                attribute_value,
            )

    def _build_feeder_attribute(
        self, attribute_id: int, value: Any = None, length: int | None = None
    ) -> tuple[str, bytes]:
        LOGGER.debug(
            "OppleCluster.build_feeder_attribute: id: %s, value: %s length: %s",
            attribute_id,
            value,
            length,
        )
        self._send_sequence = ((self._send_sequence or 0) + 1) % 256
        val = bytes([0x00, 0x02, self._send_sequence])
        val += types.int32s_be(attribute_id).serialize()
        if length is not None and value is not None:
            val += types.uint8_t(length).serialize()
        if value is not None:
            if length == 1:
                val += types.uint8_t(value).serialize()
            elif length == 2:
                val += types.uint16_t_be(value).serialize()
            elif length == 4:
                val += types.uint32_t_be(value).serialize()
            else:
                val += value
        LOGGER.debug(
            "OppleCluster.build_feeder_attribute: id: %s, cooked value: %s length: %s",
            attribute_id,
            val,
            length,
        )
        return FEEDER_ATTR_NAME, val

    def _parse_schedule(self, value: bytes) -> None:
        """Parse schedule data from the feeder and update ZCL_SCHEDULE."""
        try:
            schedule_value = value.decode("utf-8", errors="ignore").strip()
        except UnicodeDecodeError:
            return

        idx = 0
        while idx < len(schedule_value) and schedule_value[idx] not in string.hexdigits:
            idx += 1
        schedule_value = schedule_value[idx:]

        if not schedule_value:
            self._update_attribute(ZCL_SCHEDULE, "[]")
            return

        schedules = []
        schedule_parts = (
            schedule_value.split(",")
            if "," in schedule_value
            else schedule_value.split()
        )
        for part in schedule_parts:
            part = part.strip()
            if len(part) < 8:
                continue
            try:
                days_mask = int(part[0:2], 16)
                hour = int(part[2:4], 16)
                minute = int(part[4:6], 16)
                portions = int(part[6:8], 16)
            except ValueError:
                continue

            if not (hour < 24 and minute < 60 and portions > 0):
                continue

            day_name = DAYS_REVERSE_MAP.get(days_mask)
            if day_name is None:
                LOGGER.warning(
                    "OppleCluster._parse_schedule: unrecognized days bitmask "
                    "0x%02X, reporting raw mask",
                    days_mask,
                )
                day_name = f"mask_0x{days_mask:02X}"

            schedules.append(
                {
                    "days": day_name,
                    "hour": hour,
                    "minute": minute,
                    "portions": portions,
                }
            )

        if not schedules:
            LOGGER.warning(
                "OppleCluster._parse_schedule: invalid schedule payload: %s",
                value,
            )
            return

        self._update_attribute(
            ZCL_SCHEDULE, json.dumps(schedules, separators=(",", ":"))
        )

    def _encode_schedule(self, schedule_input: Any) -> bytes | None:
        """Encode a JSON schedule into a ready-to-send feeder_attr frame."""
        try:
            if isinstance(schedule_input, str):
                schedule_list = (
                    json.loads(schedule_input) if schedule_input.strip() else []
                )
            elif isinstance(schedule_input, list):
                schedule_list = schedule_input
            else:
                LOGGER.error(
                    "[0x%04X] Invalid schedule format", self._endpoint.device.nwk
                )
                return None

            if not isinstance(schedule_list, list):
                LOGGER.error(
                    "[0x%04X] Invalid schedule format", self._endpoint.device.nwk
                )
                return None

            if len(schedule_list) > MAX_SCHEDULE_ENTRIES:
                LOGGER.error(
                    "[0x%04X] Too many schedule entries (max %d)",
                    self._endpoint.device.nwk,
                    MAX_SCHEDULE_ENTRIES,
                )
                return None

            parts = []
            for schedule in schedule_list:
                if not isinstance(schedule, dict):
                    LOGGER.error(
                        "[0x%04X] Invalid schedule entry format",
                        self._endpoint.device.nwk,
                    )
                    return None

                days = schedule.get("days")
                hour = schedule.get("hour")
                minute = schedule.get("minute")
                portions = schedule.get("portions")

                if (
                    hour is None
                    or minute is None
                    or portions is None
                    or not (0 <= hour <= 23)
                    or not (0 <= minute <= 59)
                    or not (1 <= portions <= 10)
                ):
                    LOGGER.error(
                        "[0x%04X] Invalid schedule values: hour=%s, minute=%s, portions=%s",
                        self._endpoint.device.nwk,
                        hour,
                        minute,
                        portions,
                    )
                    return None

                if days not in DAYS_MAP:
                    LOGGER.error(
                        "[0x%04X] Invalid schedule days value: %r (expected one of %s)",
                        self._endpoint.device.nwk,
                        days,
                        sorted(DAYS_MAP),
                    )
                    return None

                days_mask = DAYS_MAP[days]
                parts.append(f"{days_mask:02X}{hour:02X}{minute:02X}{portions:02X}00")

            data = ",".join(parts)
            payload = data.encode() + b"\x00"

            if len(payload) > 0xFF:
                LOGGER.error(
                    "[0x%04X] Encoded schedule payload too large (%d bytes)",
                    self._endpoint.device.nwk,
                    len(payload),
                )
                return None

            _, packet = self._build_feeder_attribute(
                SCHEDULING_STRING, payload, len(payload)
            )
            return packet
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            LOGGER.error(
                "[0x%04X] Failed to encode schedule: %s",
                self._endpoint.device.nwk,
                str(e),
            )
            return None

    async def _write_schedule(
        self, schedule_val: str
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Encode and send the onboard schedule, including clears."""
        packet = self._encode_schedule(schedule_val)
        if packet is None:
            LOGGER.error(
                "[0x%04X] Failed to encode schedule; nothing sent to device",
                self._endpoint.device.nwk,
            )
            return [[foundation.WriteAttributesStatusRecord(foundation.Status.FAILURE)]]

        tv = foundation.TypeValue()
        tv.type = FEEDER_ATTR_TYPE_ID
        tv.value = types.LVBytes(packet)

        result = await self._write_attributes(
            [foundation.Attribute(FEEDER_ATTR, tv)],
            manufacturer=0x115F,
        )
        return result

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Write attributes to device with internal 'attributes' validation."""
        attributes = dict(attributes)

        schedule_key = next(
            (
                attr
                for attr in attributes
                if attr == ZCL_SCHEDULE
                or (isinstance(attr, str) and attr == "schedule")
            ),
            None,
        )

        schedule_result: list[list[foundation.WriteAttributesStatusRecord]] = []
        if schedule_key is not None:
            raw_value = attributes.pop(schedule_key)
            schedule_val = str(getattr(raw_value, "value", raw_value))
            schedule_result = await self._write_schedule(schedule_val)

            if not attributes:
                return schedule_result

        attrs = {}
        for attr, value in attributes.items():
            attr_def = self.find_attribute(attr)
            attr_id = attr_def.id
            if attr_id in ZCL_TO_AQARA:
                attribute, cooked_value = self._build_feeder_attribute(
                    ZCL_TO_AQARA[attr_id],
                    value,
                    4 if attr_def.name in ("serving_size", "portion_weight") else 1,
                )
                attrs[attribute] = cooked_value
            else:
                attrs[attr] = value

        LOGGER.debug("OppleCluster.write_attributes: %s", attrs)
        kwargs.pop("update_cache", None)
        result = await super().write_attributes(attrs, update_cache=False, **kwargs)
        return schedule_result + result if schedule_key is not None else result


(
    QuirkBuilder(None, "aqara.feeder.acn001")
    .friendly_name(manufacturer="Aqara", model="aqara.feeder.acn001")
    # The v2 entities only take over cleanly once the
    # native classes are removed (zigpy/zha#883) if the model string matches.
    .removes(OnOff.cluster_id)
    .replaces(OppleCluster)
    .adds(FeederTimeCluster)
    .enum(
        attribute_name=OppleCluster.AttributeDefs.last_feeding_source.name,
        enum_class=FeedingSource,
        cluster_id=OppleCluster.cluster_id,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.STANDARD,
        unique_id_suffix=f"{OppleCluster.cluster_id}-last_feeding_source",
        translation_key="last_feeding_source",
        fallback_name="Last feeding source",
    )
    .sensor(
        attribute_name=OppleCluster.AttributeDefs.last_feeding_size.name,
        cluster_id=OppleCluster.cluster_id,
        unique_id_suffix=f"{OppleCluster.cluster_id}-last_feeding_size",
        translation_key="last_feeding_size",
        fallback_name="Last feeding size",
    )
    .sensor(
        attribute_name=OppleCluster.AttributeDefs.portions_dispensed.name,
        cluster_id=OppleCluster.cluster_id,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unique_id_suffix=f"{OppleCluster.cluster_id}-portions_dispensed",
        translation_key="portions_dispensed_today",
        fallback_name="Portions dispensed today",
    )
    .sensor(
        attribute_name=OppleCluster.AttributeDefs.weight_dispensed.name,
        cluster_id=OppleCluster.cluster_id,
        unit=UnitOfMass.GRAMS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unique_id_suffix=f"{OppleCluster.cluster_id}-weight_dispensed",
        translation_key="weight_dispensed_today",
        fallback_name="Weight dispensed today",
    )
    .switch(
        attribute_name=OppleCluster.AttributeDefs.disable_led_indicator.name,
        cluster_id=OppleCluster.cluster_id,
        force_inverted=True,
        unique_id_suffix=f"{OppleCluster.cluster_id}-disable_led_indicator",
        translation_key="led_indicator",
        fallback_name="LED indicator",
    )
    .switch(
        attribute_name=OppleCluster.AttributeDefs.child_lock.name,
        cluster_id=OppleCluster.cluster_id,
        unique_id_suffix=f"{OppleCluster.cluster_id}-child_lock",
        translation_key="child_lock",
        fallback_name="Child lock",
    )
    .enum(
        attribute_name=OppleCluster.AttributeDefs.feeding_mode.name,
        enum_class=FeedingMode,
        cluster_id=OppleCluster.cluster_id,
        unique_id_suffix=f"{OppleCluster.cluster_id}-feeding_mode",
        translation_key="feeding_mode",
        fallback_name="Feeding mode",
    )
    .number(
        attribute_name=OppleCluster.AttributeDefs.serving_size.name,
        cluster_id=OppleCluster.cluster_id,
        min_value=1,
        max_value=10,
        mode="box",
        unique_id_suffix=f"{OppleCluster.cluster_id}-serving_size",
        translation_key="serving_size",
        fallback_name="Serving size",
    )
    .number(
        attribute_name=OppleCluster.AttributeDefs.portion_weight.name,
        cluster_id=OppleCluster.cluster_id,
        min_value=1,
        max_value=100,
        unit=UnitOfMass.GRAMS,
        mode="box",
        unique_id_suffix=f"{OppleCluster.cluster_id}-portion_weight",
        translation_key="portion_weight",
        fallback_name="Portion weight",
    )
    .binary_sensor(
        attribute_name=OppleCluster.AttributeDefs.error_detected.name,
        cluster_id=OppleCluster.cluster_id,
        entity_type=EntityType.STANDARD,
        device_class=BinarySensorDeviceClass.PROBLEM,
        unique_id_suffix=f"{OppleCluster.cluster_id}-error_detected",
        fallback_name="Error detected",
    )
    .binary_sensor(
        attribute_name=OppleCluster.AttributeDefs.battery_mode.name,
        cluster_id=OppleCluster.cluster_id,
        entity_type=EntityType.STANDARD,
        translation_key="battery_mode",
        unique_id_suffix=f"{OppleCluster.cluster_id}-battery_mode",
        fallback_name="Battery mode",
    )
    .write_attr_button(
        attribute_name=OppleCluster.AttributeDefs.feeding.name,
        attribute_value=1,
        cluster_id=OppleCluster.cluster_id,
        entity_type=EntityType.STANDARD,
        unique_id_suffix=f"{OppleCluster.cluster_id}-feeding",
        translation_key="feed",
        fallback_name="Feed",
    )
    .add_to_registry()
)
