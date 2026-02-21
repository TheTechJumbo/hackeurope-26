import uuid
import re


def generate_base_id(request_file_basename: str = None) -> str:
    """
    Generate a base unique ID for a root request.
    Uses first 12 chars of UUID4 hex for brevity.
    
    Args:
        request_file_basename: Optional, can be used for reference but not included in ID
    
    Returns:
        str: A unique ID (e.g., "a3f7c2d9e1b4")
    """
    return uuid.uuid4().hex[:12]


def create_subtask_id(parent_id: str, subtask_index: int) -> str:
    """
    Create a hierarchical task ID for a subtask.
    
    Args:
        parent_id: The parent task ID (e.g., "a3f7c2d9e1b4")
        subtask_index: The index of this subtask (0-based)
    
    Returns:
        str: Hierarchical task ID (e.g., "a3f7c2d9e1b4.0")
    """
    return f"{parent_id}.{subtask_index}"


def get_depth(task_id: str) -> int:
    """
    Determine the depth/layer of a task by counting dots.
    
    Args:
        task_id: The task ID (e.g., "a3f7c2d9e1b4.0.2.1")
    
    Returns:
        int: Depth (0 for root, 1 for first-level subtasks, etc.)
    """
    return task_id.count('.')


def get_parent_id(task_id: str) -> str:
    """
    Get the parent task ID by removing the last segment.
    
    Args:
        task_id: The task ID (e.g., "a3f7c2d9e1b4.0.2.1")
    
    Returns:
        str: Parent ID (e.g., "a3f7c2d9e1b4.0.2"), or None if root
    """
    parts = task_id.rsplit('.', 1)
    if len(parts) == 1:
        return None
    return parts[0]


def parse_task_id(task_id: str) -> dict:
    """
    Parse a task ID into its components.
    
    Args:
        task_id: The task ID (e.g., "a3f7c2d9e1b4.0.2.1")
    
    Returns:
        dict: {
            'root_id': 'a3f7c2d9e1b4',
            'path': [0, 2, 1],
            'depth': 3,
            'parent_id': 'a3f7c2d9e1b4.0.2'
        }
    """
    parts = task_id.split('.')
    root_id = parts[0]
    path = [int(p) for p in parts[1:]] if len(parts) > 1 else []
    depth = len(path)
    parent_id = get_parent_id(task_id)
    
    return {
        'root_id': root_id,
        'path': path,
        'depth': depth,
        'parent_id': parent_id,
        'full_id': task_id
    }


def format_task_id_display(task_id: str) -> str:
    """
    Format a task ID for display purposes.
    
    Args:
        task_id: The task ID (e.g., "a3f7c2d9e1b4.0.2.1")
    
    Returns:
        str: Formatted display (e.g., "a3f7c2d9e1b4 > Level 1: subtask 0 > Level 2: subtask 2 > Level 3: subtask 1")
    """
    info = parse_task_id(task_id)
    if info['depth'] == 0:
        return f"{info['root_id']} (ROOT)"
    
    display = f"{info['root_id']}"
    for level, index in enumerate(info['path'], 1):
        display += f" > L{level}[{index}]"
    return display


if __name__ == "__main__":
    # Test the ID manager
    print("Testing Task ID Manager\n")
    
    # Test root ID generation
    root_id = generate_base_id()
    print(f"Root ID: {root_id}")
    
    # Test subtask IDs
    print(f"Subtask IDs:")
    for i in range(3):
        subtask_id = create_subtask_id(root_id, i)
        print(f"  {format_task_id_display(subtask_id)}")
        
        # Nested subtasks
        for j in range(2):
            nested_id = create_subtask_id(subtask_id, j)
            print(f"    {format_task_id_display(nested_id)}")
    
    # Test depth calculation
    print(f"\nDepth tests:")
    test_ids = [root_id, create_subtask_id(root_id, 0), 
                create_subtask_id(create_subtask_id(root_id, 0), 1)]
    for tid in test_ids:
        print(f"  {tid}: depth={get_depth(tid)}")
    
    # Test parsing
    print(f"\nParsing example: a3f7c2d9e1b4.0.2.1")
    parsed = parse_task_id("a3f7c2d9e1b4.0.2.1")
    print(f"  Root: {parsed['root_id']}")
    print(f"  Path: {parsed['path']}")
    print(f"  Depth: {parsed['depth']}")
    print(f"  Parent: {parsed['parent_id']}")
