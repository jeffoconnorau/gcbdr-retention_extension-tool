from google.cloud import backupdr_v1
import inspect

print("Searching for Enums in backupdr_v1...")

# detailed inspection
for name, obj in inspect.getmembers(backupdr_v1):
    if "Workload" in name or "DataSource" in name or "Type" in name:
        print(f"\nScanning {name}:")
        try:
             # Try to print attributes if it looks like an Enum or class
             for attr in dir(obj):
                 if attr.isupper():
                     print(f"  {attr}")
        except:
            pass

print("\nChecking specifically for 'WorkloadType' or similar:")
# The proto might define it as WorkloadType
if hasattr(backupdr_v1, "WorkloadType"):
    for attr in dir(backupdr_v1.WorkloadType):
        if attr.isupper():
            print(f"  WorkloadType.{attr}")
