"""
Explore Sionna RT Scenes for Factory/Industrial Deployments
"""
import sys
sys.path.append('/home/ma012/sionna-rt-playground/venv/lib/python3.12/site-packages')

import sionna
from sionna.rt import load_scene, scene
import os

print("="*70)
print("Sionna RT Available Scenes")
print("="*70)
print()

# List of interesting scenes for factory/industrial use
scenes_to_explore = [
    ('munich', 'Large urban scene - Munich city'),
    ('etoile', 'Urban scene - Etoile area'),
    ('simple_street_canyon', 'Street canyon with buildings'),
    ('simple_street_canyon_with_cars', 'Street canyon with vehicles'),
]

print("Recommended scenes for industrial/factory deployment:")
print()

for scene_name, description in scenes_to_explore:
    print(f"📍 {scene_name}:")
    print(f"   {description}")
    
    try:
        # Try to load the scene
        if scene_name == 'munich':
            test_scene = load_scene(sionna.rt.scene.munich)
        elif scene_name == 'etoile':
            test_scene = load_scene(sionna.rt.scene.etoile)
        elif scene_name == 'simple_street_canyon':
            test_scene = load_scene(sionna.rt.scene.simple_street_canyon)
        elif scene_name == 'simple_street_canyon_with_cars':
            test_scene = load_scene(sionna.rt.scene.simple_street_canyon_with_cars)
        
        # Get scene info
        print(f"   ✓ Scene loaded successfully")
        print(f"   Objects in scene: {len(test_scene.objects) if hasattr(test_scene, 'objects') else 'N/A'}")
        
    except Exception as e:
        print(f"   ✗ Error: {str(e)[:50]}")
    
    print()

print("="*70)
print("Creating Custom Factory Scenarios")
print("="*70)
print()
print("Sionna RT allows you to:")
print("1. Load existing city scenes (munich, etoile) for outdoor industrial areas")
print("2. Use simple_street_canyon for warehouse/factory corridors")
print("3. Import custom 3D models (.xml, .obj, .stl) for specific factory layouts")
print("4. Programmatically create custom scenes with buildings and obstacles")
print()
print("For factory deployment, consider:")
print("- munich: Large-scale outdoor factory campus")
print("- etoile: Medium urban industrial area")
print("- simple_street_canyon: Indoor warehouse/corridor simulation")
print("- Custom scene: Import your factory's 3D CAD model")
print()

