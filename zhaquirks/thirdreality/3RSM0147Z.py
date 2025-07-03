"""Third Reality 3RSM0147Z soil moisture and temperature sensor."""

from zigpy.quirks.v2 import (
    QuirkBuilder,
    ReportingConfig,
    SensorDeviceClass,
    SensorStateClass,
)
from zigpy.quirks.v2.homeassistant import PERCENTAGE
from zigpy.zcl.clusters.measurement import RelativeHumidity

(
    QuirkBuilder("Third Reality, Inc", "3RSM0147Z")
    # Ignore the default relative humidity entity
    .prevent_default_entity_creation(
        cluster_id=RelativeHumidity.cluster_id,
        endpoint_id=1,
        function=lambda entity: entity.translation_key is None,
    )
    # And instead create a new one
    .sensor(
        attribute_name=RelativeHumidity.AttributeDefs.measured_value.name,
        cluster_id=RelativeHumidity.cluster_id,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.MOISTURE,
        unit=PERCENTAGE,
        divisor=100,
        reporting_config=ReportingConfig(
            min_interval=30,
            max_interval=900,
            reportable_change=100,
        ),
        translation_key="soil_moisture",
        fallback_name="Soil moisture",
        primary=True,
        # To "migrate" existing entities, clone the unique ID suffix of the relative
        # humidity entity
        unique_id_suffix="1029",
    )
    .add_to_registry()
)
