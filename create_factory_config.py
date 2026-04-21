#!/usr/bin/env python3
"""
Generate comprehensive factory deployment configuration JSON
"""
import json
from datetime import datetime

config = {
    "metadata": {
        "version": "1.0.0",
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": "5G Private Network Configuration for Smart Factory",
        "project": "Sionna RT + OAI + free5GC Integration"
    },

    "deployment": {
        "environment": "industrial_factory",
        "dimensions": {
            "length_m": 100,
            "width_m": 60,
            "height_m": 10,
            "description": "Large manufacturing facility"
        },
        "use_cases": [
            "Autonomous Guided Vehicles (AGV)",
            "Robotic Arms (URLLC)",
            "Augmented Reality (AR/VR)",
            "8K Video Surveillance",
            "IoT Sensors (mMTC)"
        ]
    },

    "radio_configurations": {
        "sub6_ghz": {
            "name": "Sub-6 GHz CBRS",
            "carrier_frequency_ghz": 3.7,
            "carrier_frequency_hz": 3700000000,
            "bandwidth_mhz": 20,
            "band": "CBRS Band 48",
            "duplex_mode": "TDD",
            "numerology": 1,
            "subcarrier_spacing_khz": 30,
            "tti_us": 125,
            "wavelength_mm": 81.08,
            "coverage_characteristics": "Wide area, good penetration",
            "typical_range_m": 200
        },
        "mmwave": {
            "name": "mmWave 28 GHz",
            "carrier_frequency_ghz": 28,
            "carrier_frequency_hz": 28000000000,
            "bandwidth_mhz": 100,
            "band": "5G NR n257/n258",
            "duplex_mode": "TDD",
            "numerology": 3,
            "subcarrier_spacing_khz": 120,
            "tti_us": 62.5,
            "wavelength_mm": 10.71,
            "coverage_characteristics": "High capacity, short range, beamforming essential",
            "typical_range_m": 50
        }
    },

    "gnb_deployments": {
        "count": 3,
        "deployment_type": "ceiling_mounted",
        "antenna_configuration": {
            "array_type": "URA",
            "num_rows": 8,
            "num_cols": 8,
            "total_elements": 64,
            "vertical_spacing": 0.5,
            "horizontal_spacing": 0.5,
            "pattern": "isotropic",
            "polarization": "vertical"
        },
        "gnbs": [
            {
                "id": "gNB1",
                "name": "Northwest AP",
                "position_m": [20, 20, 9],
                "orientation_deg": [0, 0, 0],
                "tx_power_dbm": 30,
                "coverage_area": "Assembly zone",
                "connected_devices_sub6": ["AGV-1", "IoT_Gateway"],
                "connected_devices_mmwave": ["AGV-1", "Edge_Server"]
            },
            {
                "id": "gNB2",
                "name": "Central AP",
                "position_m": [50, 30, 9],
                "orientation_deg": [0, 0, 0],
                "tx_power_dbm": 30,
                "coverage_area": "Main production line",
                "connected_devices_sub6": ["AGV-2", "Robot-1", "Robot-2", "Sensor-1", "Camera-1"],
                "connected_devices_mmwave": ["AGV-2", "Robot-1", "8K_Camera", "AR_Station"]
            },
            {
                "id": "gNB3",
                "name": "Southeast AP",
                "position_m": [80, 20, 9],
                "orientation_deg": [0, 0, 0],
                "tx_power_dbm": 30,
                "coverage_area": "Quality control & packaging",
                "connected_devices_sub6": ["AR_Device"],
                "connected_devices_mmwave": ["Robot-2", "VR_Device"]
            }
        ]
    },

    "device_deployments": {
        "count": 8,
        "antenna_configuration": {
            "array_type": "URA",
            "num_rows": 2,
            "num_cols": 2,
            "total_elements": 4,
            "vertical_spacing": 0.5,
            "horizontal_spacing": 0.5,
            "pattern": "isotropic",
            "polarization": "vertical"
        },
        "devices": [
            {
                "id": "AGV-1",
                "type": "Autonomous Guided Vehicle",
                "position_m": [15, 15, 1.5],
                "slice": "AGV_AMR",
                "application": "Material transport",
                "mobility": "mobile",
                "max_speed_kmh": 10,
                "requirements": {
                    "latency_ms": 10,
                    "throughput_mbps": 50,
                    "reliability_percent": 99.99
                }
            },
            {
                "id": "AGV-2",
                "type": "Autonomous Mobile Robot",
                "position_m": [45, 25, 1.5],
                "slice": "AGV_AMR",
                "application": "Inventory management",
                "mobility": "mobile",
                "max_speed_kmh": 8,
                "requirements": {
                    "latency_ms": 10,
                    "throughput_mbps": 50,
                    "reliability_percent": 99.99
                }
            },
            {
                "id": "Robot-1",
                "type": "Robotic Arm (URLLC)",
                "position_m": [55, 35, 1.5],
                "slice": "URLLC",
                "application": "Precision assembly",
                "mobility": "stationary",
                "requirements": {
                    "latency_ms": 1,
                    "throughput_mbps": 10,
                    "reliability_percent": 99.9999
                }
            },
            {
                "id": "Robot-2",
                "type": "Collaborative Robot",
                "position_m": [75, 15, 1.5],
                "slice": "URLLC",
                "application": "Quality inspection",
                "mobility": "stationary",
                "requirements": {
                    "latency_ms": 1,
                    "throughput_mbps": 10,
                    "reliability_percent": 99.9999
                }
            },
            {
                "id": "Sensor-1",
                "type": "IoT Sensor Gateway",
                "position_m": [50, 40, 1.5],
                "slice": "IoT_mMTC",
                "application": "Environmental monitoring",
                "mobility": "stationary",
                "requirements": {
                    "latency_ms": 100,
                    "throughput_kbps": 100,
                    "reliability_percent": 99.9
                }
            },
            {
                "id": "Camera-1",
                "type": "8K Surveillance Camera",
                "position_m": [60, 25, 3.0],
                "slice": "AR_VR_Video",
                "application": "Security & process monitoring",
                "mobility": "stationary",
                "requirements": {
                    "latency_ms": 30,
                    "throughput_mbps": 200,
                    "reliability_percent": 99.99
                }
            },
            {
                "id": "AR_Device",
                "type": "AR Headset",
                "position_m": [85, 25, 1.7],
                "slice": "AR_VR_Video",
                "application": "Maintenance guidance",
                "mobility": "mobile",
                "max_speed_kmh": 5,
                "requirements": {
                    "latency_ms": 20,
                    "throughput_mbps": 100,
                    "reliability_percent": 99.99
                }
            },
            {
                "id": "IoT_Gateway",
                "type": "IoT Gateway Hub",
                "position_m": [25, 10, 2.0],
                "slice": "IoT_mMTC",
                "application": "Sensor aggregation (50+ sensors)",
                "mobility": "stationary",
                "requirements": {
                    "latency_ms": 100,
                    "throughput_mbps": 5,
                    "reliability_percent": 99.9
                }
            }
        ]
    },

    "network_slicing": {
        "enabled": True,
        "num_slices": 4,
        "slices": [
            {
                "slice_id": 1,
                "name": "AGV_AMR",
                "sst": 1,
                "sd": "000001",
                "type": "eMBB",
                "5qi": 7,
                "priority": 20,
                "description": "Autonomous vehicles and mobile robots",
                "requirements": {
                    "latency_budget_ms": 10,
                    "jitter_ms": 2,
                    "packet_loss_rate": 0.0001,
                    "throughput_guaranteed_mbps": 50,
                    "throughput_max_mbps": 200
                },
                "resource_allocation": {
                    "prb_allocation_percent": 30,
                    "user_count": 2
                },
                "qos_flows": [
                    {
                        "qfi": 1,
                        "5qi": 7,
                        "gfbr_mbps": 50,
                        "mfbr_mbps": 200,
                        "arp_priority": 2,
                        "arp_preemption_capability": "MAY_PREEMPT",
                        "arp_preemption_vulnerability": "NOT_PREEMPTABLE"
                    }
                ]
            },
            {
                "slice_id": 2,
                "name": "URLLC",
                "sst": 2,
                "sd": "000002",
                "type": "URLLC",
                "5qi": 82,
                "priority": 10,
                "description": "Ultra-reliable low-latency for robotic control",
                "requirements": {
                    "latency_budget_ms": 1,
                    "jitter_ms": 0.1,
                    "packet_loss_rate": 0.000001,
                    "throughput_guaranteed_mbps": 10,
                    "throughput_max_mbps": 50,
                    "reliability_percent": 99.9999
                },
                "resource_allocation": {
                    "prb_allocation_percent": 25,
                    "user_count": 2,
                    "grant_free_enabled": True,
                    "scheduling_policy": "strict_priority"
                },
                "qos_flows": [
                    {
                        "qfi": 2,
                        "5qi": 82,
                        "gfbr_mbps": 10,
                        "mfbr_mbps": 50,
                        "arp_priority": 1,
                        "arp_preemption_capability": "MAY_PREEMPT",
                        "arp_preemption_vulnerability": "NOT_PREEMPTABLE"
                    }
                ]
            },
            {
                "slice_id": 3,
                "name": "AR_VR_Video",
                "sst": 1,
                "sd": "000003",
                "type": "eMBB",
                "5qi": 2,
                "priority": 30,
                "description": "AR/VR and high-definition video streaming",
                "requirements": {
                    "latency_budget_ms": 20,
                    "jitter_ms": 5,
                    "packet_loss_rate": 0.0001,
                    "throughput_guaranteed_mbps": 100,
                    "throughput_max_mbps": 500
                },
                "resource_allocation": {
                    "prb_allocation_percent": 35,
                    "user_count": 2
                },
                "qos_flows": [
                    {
                        "qfi": 3,
                        "5qi": 2,
                        "gfbr_mbps": 100,
                        "mfbr_mbps": 500,
                        "arp_priority": 3,
                        "arp_preemption_capability": "NOT_PREEMPT",
                        "arp_preemption_vulnerability": "PREEMPTABLE"
                    }
                ]
            },
            {
                "slice_id": 4,
                "name": "IoT_mMTC",
                "sst": 3,
                "sd": "000004",
                "type": "mMTC",
                "5qi": 9,
                "priority": 40,
                "description": "Massive IoT sensor networks",
                "requirements": {
                    "latency_budget_ms": 100,
                    "jitter_ms": 20,
                    "packet_loss_rate": 0.001,
                    "throughput_guaranteed_kbps": 100,
                    "throughput_max_mbps": 10,
                    "device_density_per_km2": 100000
                },
                "resource_allocation": {
                    "prb_allocation_percent": 10,
                    "user_count": 2,
                    "edrx_enabled": True,
                    "psm_enabled": True
                },
                "qos_flows": [
                    {
                        "qfi": 4,
                        "5qi": 9,
                        "gfbr_kbps": 100,
                        "mfbr_mbps": 10,
                        "arp_priority": 4,
                        "arp_preemption_capability": "NOT_PREEMPT",
                        "arp_preemption_vulnerability": "PREEMPTABLE"
                    }
                ]
            }
        ]
    },

    "beamforming": {
        "algorithm": "MRT",
        "full_name": "Maximum Ratio Transmission",
        "description": "Conjugate beamforming using channel state information",
        "parameters": {
            "method": "conjugate_transpose",
            "normalization": "per_antenna",
            "csi_feedback_period_ms": 10,
            "codebook": "Type1-SinglePanel",
            "num_csi_rs_ports": 64,
            "precoding_granularity": "wideband"
        },
        "implementation": {
            "formula": "w = conj(H) / ||H||",
            "input": "Channel matrix H [num_rx, num_rx_ant, num_tx, num_tx_ant, num_paths]",
            "output": "Beamforming weights w [num_tx, num_tx_ant]",
            "normalization": "Per-antenna power normalization"
        },
        "performance": {
            "beamforming_gain_db": {
                "sub6_ghz": 18.06,
                "mmwave": 18.06
            },
            "spatial_multiplexing_layers": 8,
            "effective_isotropic_radiated_power_dbm": {
                "sub6_ghz": 48.06,
                "mmwave": 48.06
            }
        }
    },

    "performance_results": {
        "sub6_ghz_3700mhz": {
            "frequency_ghz": 3.7,
            "bandwidth_mhz": 20,
            "summary": {
                "avg_sinr_db": 57.09,
                "avg_throughput_mbps": 379.33,
                "total_capacity_mbps": 3034.61,
                "avg_latency_us": 325,
                "coverage_percent": 100,
                "devices_excellent": 8,
                "devices_good": 0,
                "devices_poor": 0
            },
            "latency_breakdown": {
                "tti_us": 125,
                "propagation_us": 0.43,
                "processing_us": 200,
                "total_us": 325
            },
            "per_device_results": [
                {"device": "AGV-1", "sinr_db": 59.31, "throughput_mbps": 394.05, "serving_gnb": "gNB1", "quality": "excellent"},
                {"device": "AGV-2", "sinr_db": 52.59, "throughput_mbps": 349.39, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "Robot-1", "sinr_db": 58.64, "throughput_mbps": 389.60, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "Robot-2", "sinr_db": 52.85, "throughput_mbps": 351.13, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "Sensor-1", "sinr_db": 59.24, "throughput_mbps": 393.56, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "Camera-1", "sinr_db": 58.16, "throughput_mbps": 386.38, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "AR_Device", "sinr_db": 59.22, "throughput_mbps": 393.42, "serving_gnb": "gNB3", "quality": "excellent"},
                {"device": "IoT_Gateway", "sinr_db": 56.76, "throughput_mbps": 377.09, "serving_gnb": "gNB1", "quality": "excellent"}
            ],
            "application_requirements_met": {
                "AGV": True,
                "URLLC": True,
                "AR_VR": True,
                "IoT": True
            }
        },
        "mmwave_28ghz": {
            "frequency_ghz": 28,
            "bandwidth_mhz": 100,
            "summary": {
                "avg_sinr_db": 39.40,
                "avg_throughput_mbps": 1308.73,
                "total_capacity_mbps": 10469.81,
                "avg_latency_us": 163,
                "coverage_percent": 100,
                "devices_excellent": 8,
                "devices_good": 0,
                "devices_poor": 0
            },
            "latency_breakdown": {
                "tti_us": 62.5,
                "propagation_us": 0.43,
                "processing_us": 100,
                "total_us": 163
            },
            "per_device_results": [
                {"device": "AGV-1", "sinr_db": 41.32, "throughput_mbps": 1373.40, "latency_us": 163, "serving_gnb": "gNB1", "quality": "excellent"},
                {"device": "AGV-2", "sinr_db": 35.37, "throughput_mbps": 1175.46, "latency_us": 163, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "Robot-1", "sinr_db": 41.15, "throughput_mbps": 1367.86, "latency_us": 163, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "Robot-2", "sinr_db": 34.74, "throughput_mbps": 1154.94, "latency_us": 163, "serving_gnb": "gNB3", "quality": "excellent"},
                {"device": "8K_Camera", "sinr_db": 41.61, "throughput_mbps": 1382.80, "latency_us": 163, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "AR_Station", "sinr_db": 40.57, "throughput_mbps": 1348.96, "latency_us": 163, "serving_gnb": "gNB2", "quality": "excellent"},
                {"device": "VR_Device", "sinr_db": 41.82, "throughput_mbps": 1389.62, "latency_us": 163, "serving_gnb": "gNB3", "quality": "excellent"},
                {"device": "Edge_Server", "sinr_db": 38.58, "throughput_mbps": 1282.80, "latency_us": 163, "serving_gnb": "gNB1", "quality": "excellent"}
            ],
            "application_requirements_met": {
                "AGV": True,
                "URLLC": True,
                "AR_VR": True,
                "8K_Video": True,
                "Edge_Computing": True
            }
        },
        "comparison": {
            "throughput_improvement_mmwave": "3.45x",
            "latency_improvement_mmwave": "2.0x",
            "sinr_advantage_sub6": "17.69 dB",
            "total_capacity_improvement": "3.45x",
            "recommendation": "Use 28 GHz for high-throughput applications, 3.7 GHz for coverage"
        }
    },

    "channel_model": {
        "method": "ray_tracing",
        "tool": "Sionna RT 2.0.1",
        "scene": "simple_street_canyon",
        "scene_dimensions_m": [100, 60, 10],
        "parameters": {
            "max_depth": 5,
            "num_paths": "variable (scene-dependent)",
            "path_loss_model": "geometric + material attenuation",
            "diffraction": True,
            "scattering": True,
            "reflection": True,
            "polarization": "vertical"
        },
        "propagation_characteristics": {
            "sub6_ghz": {
                "typical_num_paths": 15,
                "delay_spread_ns": 120,
                "path_loss_exponent": 2.8,
                "penetration_loss_db_per_wall": 5
            },
            "mmwave": {
                "typical_num_paths": 8,
                "delay_spread_ns": 45,
                "path_loss_exponent": 3.5,
                "penetration_loss_db_per_wall": 15,
                "oxygen_absorption_db_per_km": 15
            }
        },
        "cir_computation": {
            "update_interval_s": 1.0,
            "caching": True,
            "output_format": {
                "real": "float32",
                "imag": "float32",
                "delays": "float32",
                "shape": "[num_rx, num_rx_ant, num_tx, num_tx_ant, num_paths]"
            }
        }
    },

    "integration_settings": {
        "architecture": "Sionna RT + OAI + free5GC",
        "components": {
            "sionna_rt": {
                "version": "2.0.1",
                "location": "/home/ma012/sionna-rt-playground",
                "python_version": "3.12.3",
                "cuda_version": "12.6",
                "pytorch_version": "2.11.0+cu130",
                "gpu": "RTX 4080 SUPER (16GB VRAM)",
                "purpose": "Realistic channel modeling with ray tracing"
            },
            "channel_emulator": {
                "script": "/home/ma012/5g-integration/channel_emulator.py",
                "protocol": "ZMQ",
                "port": 5555,
                "method": "CIR convolution",
                "update_rate_hz": 1.0,
                "purpose": "Bridge between Sionna RT and OAI"
            },
            "oai_ran": {
                "version": "develop branch",
                "location": "/home/ma012/oai",
                "components": ["gNB", "nrUE"],
                "mode": "5G NR Standalone (SA)",
                "build_time_minutes": "30-60",
                "purpose": "5G RAN implementation"
            },
            "free5gc": {
                "version": "4.2.1",
                "location": "/home/ma012/free5gc-compose",
                "deployment": "Docker Compose",
                "network": "172.20.0.0/24",
                "components": {
                    "control_plane": ["AMF", "SMF", "NRF", "NSSF", "PCF", "UDM", "UDR", "AUSF", "NEF"],
                    "user_plane": ["UPF"],
                    "database": ["MongoDB"],
                    "management": ["WebUI"]
                },
                "interfaces": {
                    "n2": "172.20.0.100:38412 (AMF)",
                    "n3": "172.20.0.101 (UPF GTP-U)"
                },
                "ue_ip_pool": "10.60.0.0/16",
                "purpose": "5G Core Network"
            }
        },
        "data_flow": [
            "Sionna RT computes realistic CIR using ray tracing",
            "Channel emulator receives CIR via Python API",
            "OAI gNB sends baseband IQ samples to channel emulator (ZMQ)",
            "Channel emulator applies CIR convolution to IQ samples",
            "Modified IQ samples sent back to OAI (realistic channel effects)",
            "OAI gNB connects to free5GC AMF (N2 interface)",
            "OAI UE registers with free5GC",
            "Data traffic flows through UPF (N3 interface)",
            "End-to-end realistic 5G network with Sionna RT propagation"
        ],
        "deployment_status": {
            "sionna_rt": "✅ Operational (verified with simulations)",
            "free5gc": "⚠️ Partial (12/17 containers, UPF needs GTP5G)",
            "channel_emulator": "✅ Code ready",
            "oai": "⏳ Cloned, needs building (30-60 min)",
            "gtp5g": "❌ Not installed (requires sudo)",
            "integration": "⏳ Pending OAI build and GTP5G installation"
        },
        "next_steps": [
            "Install GTP5G kernel module (sudo ./install_gtp5g.sh)",
            "Build OAI gNB and nrUE (./build_oai.sh)",
            "Configure OAI to connect to free5GC",
            "Start all components and test end-to-end",
            "Measure real-world performance with Sionna RT effects"
        ]
    },

    "references": {
        "sionna_rt": "https://nvlabs.github.io/sionna/",
        "free5gc": "https://free5gc.org/",
        "oai": "https://gitlab.eurecom.fr/oai/openairinterface5g",
        "research_paper": "https://arxiv.org/html/2503.12177v3",
        "3gpp_5qi": "TS 23.501 Section 5.7.4",
        "3gpp_network_slicing": "TS 23.501 Section 5.15"
    }
}

# Write to file
output_file = '/home/ma012/sionna-rt-playground/factory_config.json'
with open(output_file, 'w') as f:
    json.dump(config, f, indent=2)

print(f"✓ Configuration written to: {output_file}")
print(f"✓ File size: {len(json.dumps(config, indent=2))} bytes")
print(f"✓ Sections: {len(config)} top-level categories")
print(f"✓ Network slices: {config['network_slicing']['num_slices']}")
print(f"✓ gNB deployments: {config['gnb_deployments']['count']}")
print(f"✓ Device deployments: {config['device_deployments']['count']}")
