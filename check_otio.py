# check_otio.py
import opentimelineio as otio
import sys

print(f"Python version: {sys.version}")
print(f"OTIO version: {otio.__version__}")
print("\nAvailable OTIO Adapters:")
print("-" * 25)
try:
    adapters = otio.adapters.available_adapter_names()
    if adapters:
        for name in sorted(adapters):
            print(f"- {name}")
    else:
         print("No adapters found!")
except Exception as e:
    print(f"Error listing adapters: {e}")

print("-" * 25)
# Check specific adapters
aaf_available = 'aaf' in adapters or 'aaf_adapter' in adapters # Check common names
xml_available = 'xml' in adapters or 'fcpxml' in adapters # Check common names
print(f"AAF adapter likely available: {aaf_available}")
print(f"XML/FCPXML adapter likely available: {xml_available}")