# Hierarchical Task ID System

## Overview

The hierarchical task ID system creates unique, deterministic IDs for tasks and subtasks based on their position in the decomposition tree. Depth/layer is determined by counting dots in the ID.

## ID Format

```
[root_id].[level1_index].[level2_index]...[levelN_index]
```

### Examples

- **Root task**: `b7eb2078a17e` (0 dots, depth 0)
- **First-level subtask**: `b7eb2078a17e.0` (1 dot, depth 1)
- **Second-level subtask**: `b7eb2078a17e.0.2` (2 dots, depth 2)
- **Third-level subtask**: `b7eb2078a17e.0.2.1` (3 dots, depth 3)

## Depth Calculation

The depth of any task ID is simply the count of dots:

```python
def get_depth(task_id):
    return task_id.count('.')
```

## Generation Process

### Step 1: Complexity Evaluation
When `complexity_evaluator.py --batch` runs:

1. **Generate unique root ID** for each request from sample_requests
   - Uses 12-character hex string from UUID4
   - Example: `b7eb2078a17e`

2. **Save in cleaned_requests**:
   ```json
   {
     "task_id": "b7eb2078a17e",
     "input": "Research customer insights...",
     "complexity_score": 80,
     "eval_gen": 1,
     "subtasks": []
   }
   ```

3. **Save full log in logs/**:
   ```json
   {
     "task_id": "b7eb2078a17e",
     "request_id": "original_request_id",
     "complexity_evaluation": {...},
     ...
   }
   ```

### Step 2: Task Decomposition
When `task_decomposer.py [threshold]` runs on tasks with complexity > threshold:

1. **Create hierarchical subtask IDs** using parent ID
   - Subtask 0: `b7eb2078a17e.0`
   - Subtask 1: `b7eb2078a17e.1`
   - Subtask 2: `b7eb2078a17e.2`
   - etc.

2. **Save decomposed tasks in cleaned_requests**:
   ```json
   {
     "task_id": "b7eb2078a17e",
     "subtasks": [
       {
         "task_id": "b7eb2078a17e.0",
         "input": "Gather data...",
         "complexity_score": 60,
         "subtasks": []
       },
       {
         "task_id": "b7eb2078a17e.1",
         "input": "Process data...",
         "complexity_score": 70,
         "subtasks": []
       },
       ...
     ]
   }
   ```

3. **Save decomposition log in logs/**:
   ```json
   {
     "parent_task_id": "b7eb2078a17e",
     "subtask_ids": ["b7eb2078a17e.0", "b7eb2078a17e.1", ...],
     "subtask_count": 12,
     ...
   }
   ```

### Step 3: Recursive Decomposition
When decomposing high-complexity subtasks:

1. If subtask `b7eb2078a17e.0` has complexity > threshold
2. Create nested subtasks:
   - `b7eb2078a17e.0.0`
   - `b7eb2078a17e.0.1`
   - `b7eb2078a17e.0.2`
   - etc.

3. Each can be further decomposed:
   - `b7eb2078a17e.0.0.0`
   - `b7eb2078a17e.0.0.1`
   - etc.

## Task Tree Structure

```
b7eb2078a17e (Root, Depth 0, Complexity 80)
├─ b7eb2078a17e.0 (Depth 1, Complexity 60)
│  ├─ b7eb2078a17e.0.0 (Depth 2, Complexity 45)
│  ├─ b7eb2078a17e.0.1 (Depth 2, Complexity 50)
│  └─ b7eb2078a17e.0.2 (Depth 2, Complexity 40)
├─ b7eb2078a17e.1 (Depth 1, Complexity 70)
│  ├─ b7eb2078a17e.1.0 (Depth 2, Complexity 55)
│  └─ b7eb2078a17e.1.1 (Depth 2, Complexity 60)
├─ b7eb2078a17e.2 (Depth 1, Complexity 40)
...
```

## Utilities

### `task_id_manager.py`

Provides utility functions:

```python
from task_id_manager import (
    generate_base_id,          # Create new root ID
    create_subtask_id,         # Create hierarchical ID
    get_depth,                 # Count dots to determine depth
    get_parent_id,             # Get parent ID by removing last segment
    parse_task_id,             # Parse ID into components
    format_task_id_display     # Format for display
)

# Examples
root_id = generate_base_id()                    # "b7eb2078a17e"
subtask_id = create_subtask_id(root_id, 0)     # "b7eb2078a17e.0"
depth = get_depth(subtask_id)                  # 1
parent = get_parent_id(subtask_id)             # "b7eb2078a17e"

info = parse_task_id("b7eb2078a17e.0.2")
# Returns:
# {
#   'root_id': 'b7eb2078a17e',
#   'path': [0, 2],
#   'depth': 2,
#   'parent_id': 'b7eb2078a17e.0',
#   'full_id': 'b7eb2078a17e.0.2'
# }
```

## Data Flow

```
sample_requests/
├─ request_file.json

         ↓ complexity_evaluator.py --batch

cleaned_requests/
├─ request_file.json
│  {
│    "task_id": "b7eb2078a17e",
│    "complexity_score": 80,
│    "subtasks": []
│  }

logs/
├─ log_request_file.json

         ↓ task_decomposer.py [threshold]

cleaned_requests/
├─ request_file.json
│  {
│    "task_id": "b7eb2078a17e",
│    "complexity_score": 80,
│    "subtasks": [
│      {"task_id": "b7eb2078a17e.0", "complexity_score": 60, ...},
│      {"task_id": "b7eb2078a17e.1", "complexity_score": 70", ...},
│      ...
│    ]
│  }

logs/
├─ log_request_file.json
├─ decomp_log_request_file.json
```

## Key Features

1. **Deterministic**: IDs are generated based on position in tree, not random
2. **Self-describing**: Depth is immediately visible from dot count
3. **Hierarchical**: Parent-child relationships are encoded in the ID
4. **Traceable**: Can parse back to find root, path, and parent
5. **Scalable**: Supports arbitrary depth of decomposition
6. **Reversible**: Can reconstruct tree structure from IDs alone

## Example: Real Task Hierarchy

```
Root Task: b7eb2078a17e
  Complexity: 80
  Input: "Research customer insights to produce cohesive blogs, 
          videos, and social posts across all channels..."

Subtasks (Depth 1):
  1. b7eb2078a17e.0
     Complexity: 60
     Input: "Gather quantitative and qualitative data about 
             customer preferences..."

  2. b7eb2078a17e.1
     Complexity: 70
     Input: "Process collected data to extract actionable insights..."

  3. b7eb2078a17e.2
     Complexity: 40
     Input: "Generate a list of blog, video, and social post topics..."

  ... (9 more subtasks)
```

All 12 subtasks are at Depth 1 (one dot in task ID), making them directly comparable and sortable by complexity.
