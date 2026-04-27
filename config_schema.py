from pydantic import BaseModel, Field, field_validator
from typing import List, Literal


class AntennaArrayConfig(BaseModel):
    """Antenna array configuration"""
    rows: int = Field(gt=0, description="Number of antenna rows")
    cols: int = Field(gt=0, description="Number of antenna columns")
    spacing: float = Field(gt=0, description="Antenna spacing in wavelengths")


class MovingReceiverConfig(BaseModel):
    """Moving receiver (robot) configuration"""
    type: Literal["AGV", "AMR", "Robot"] = Field(description="Type of mobile robot")
    start: List[float] = Field(min_length=3, max_length=3, description="Start position [x, y, z]")
    end: List[float] = Field(min_length=3, max_length=3, description="End position [x, y, z]")
    steps: int = Field(default=10, gt=0, le=100, description="Number of movement steps")
    
    @field_validator('start', 'end')
    @classmethod
    def validate_position(cls, v):
        if len(v) != 3:
            raise ValueError('Position must have exactly 3 coordinates [x, y, z]')
        return v


class SimulationConfig(BaseModel):
    """Main simulation configuration"""
    scene: str = Field(description="Scene name (e.g., 'etoile', 'munich')")
    frequency: float = Field(gt=0, description="Carrier frequency in Hz")
    max_depth: int = Field(ge=0, le=10, description="Maximum ray reflection depth")
    beamforming_method: Literal["MRT", "MMSE"] = Field(
        default="MMSE",
        description="Beamforming algorithm: MRT (single-user) or MMSE (multi-user)"
    )
    use_statistical_channel: bool = Field(
        default=False,
        description="Use statistical channel model (fast) instead of ray tracing (accurate)"
    )
    noise_variance: float = Field(
        default=1e-8,
        gt=0,
        description="Noise variance for MMSE beamforming (σ²)"
    )
    tx_array: AntennaArrayConfig = Field(description="Transmitter antenna array config")
    rx_array: AntennaArrayConfig = Field(description="Receiver antenna array config")
    transmitters: List[List[float]] = Field(
        min_length=1,
        description="List of transmitter positions [[x, y, z], ...]")
    static_receivers: List[List[float]] = Field(
        default=[],
        description="List of static receiver positions [[x, y, z], ...]")
    moving_receivers: List[MovingReceiverConfig] = Field(
        default=[],
        description="List of moving receiver configurations")
    
    @field_validator('transmitters', 'static_receivers')
    @classmethod
    def validate_positions(cls, v):
        for pos in v:
            if len(pos) != 3:
                raise ValueError('Each position must have exactly 3 coordinates [x, y, z]')
        return v
    
    @field_validator('moving_receivers')
    @classmethod
    def validate_moving_receivers(cls, v):
        if len(v) > 10:
            raise ValueError('Maximum 10 moving receivers allowed')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "scene": "etoile",
                "frequency": 3.5e9,
                "max_depth": 3,
                "beamforming_method": "MMSE",
                "use_statistical_channel": True,
                "noise_variance": 1e-8,
                "tx_array": {"rows": 4, "cols": 4, "spacing": 0.5},
                "rx_array": {"rows": 1, "cols": 1, "spacing": 0.5},
                "transmitters": [[8.5, 21.0, 27.0], [8.5, -8.0, 27.0]],
                "static_receivers": [[14.0, 5.8, 1.5]],
                "moving_receivers": [
                    {
                        "type": "AGV",
                        "start": [2.0, 8.3, 1.5],
                        "end": [15.0, 8.3, 1.5],
                        "steps": 20
                    }
                ]
            }
        }


def load_config(config_path: str = "config.json") -> SimulationConfig:
    """Load and validate configuration from JSON file"""
    import json
    
    with open(config_path, 'r') as f:
        config_dict = json.load(f)
    
    try:
        config = SimulationConfig(**config_dict)
        return config
    except Exception as e:
        print(f"Error validating configuration: {e}")
        raise
