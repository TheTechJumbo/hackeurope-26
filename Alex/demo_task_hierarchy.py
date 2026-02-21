import json
import os
import glob
from task_id_manager import parse_task_id, get_depth, format_task_id_display


BASE_DIR = os.path.dirname(__file__)
CLEANED_DIR = os.path.join(BASE_DIR, "cleaned_requests")


def display_task_hierarchy(request_data, indent=0):
    """
    Display task hierarchy with visual formatting.
    
    Args:
        request_data: The request dict with tasks and subtasks
        indent: Current indentation level
    """
    task_id = request_data.get("task_id", "ROOT")
    input_text = request_data.get("input", "")[:70]
    complexity = request_data.get("complexity_score", "N/A")
    depth = get_depth(task_id)
    
    # Visual tree formatting
    prefix = "  " * indent + "├─ " if indent > 0 else "ROOT: "
    
    print(f"{prefix}[{task_id}] (Depth: {depth}, Complexity: {complexity})")
    print(f"{'  ' * indent}   └─ {input_text}...")
    
    # Recursively display subtasks
    subtasks = request_data.get("subtasks", [])
    for i, subtask in enumerate(subtasks):
        is_last = (i == len(subtasks) - 1)
        display_task_hierarchy(subtask, indent + 1)


def analyze_cleaned_requests():
    """
    Analyze all cleaned requests and display task hierarchies.
    """
    json_files = glob.glob(os.path.join(CLEANED_DIR, "*.json"))
    
    print("=" * 100)
    print("TASK HIERARCHY ANALYSIS")
    print("=" * 100)
    print()
    
    for request_file in sorted(json_files):
        try:
            with open(request_file, "r", encoding="utf-8") as f:
                request_data = json.load(f)
            
            filename = os.path.basename(request_file)
            print(f"\nFile: {filename}")
            print("-" * 100)
            
            display_task_hierarchy(request_data)
            
            # Count statistics
            def count_tasks(data):
                count = 1
                for subtask in data.get("subtasks", []):
                    count += count_tasks(subtask)
                return count
            
            total_tasks = count_tasks(request_data)
            print(f"\nTotal tasks in hierarchy: {total_tasks}")
            print()
            
        except Exception as e:
            print(f"Error processing {os.path.basename(request_file)}: {e}")


def show_task_id_examples():
    """
    Show examples of how task IDs work.
    """
    print("\n" + "=" * 100)
    print("TASK ID FORMAT EXAMPLES")
    print("=" * 100)
    print()
    
    examples = [
        "b7eb2078a17e",           # Root: 0 dots (depth 0)
        "b7eb2078a17e.0",         # First subtask: 1 dot (depth 1)
        "b7eb2078a17e.0.2",       # Nested: 2 dots (depth 2)
        "b7eb2078a17e.0.2.1",     # Deep nesting: 3 dots (depth 3)
    ]
    
    print("Task ID Format: [root_id].[level1_index].[level2_index]...[levelN_index]")
    print()
    print("Depth is determined by counting dots:")
    print()
    
    for task_id in examples:
        info = parse_task_id(task_id)
        print(f"  Task ID: {task_id}")
        print(f"    Root ID: {info['root_id']}")
        print(f"    Path: {info['path']}")
        print(f"    Depth: {info['depth']}")
        print(f"    Display: {format_task_id_display(task_id)}")
        print()


if __name__ == "__main__":
    show_task_id_examples()
    analyze_cleaned_requests()
