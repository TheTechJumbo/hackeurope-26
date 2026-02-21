import os
import json
import glob
from pathlib import Path


BASE_DIR = os.path.dirname(__file__)
CLEANED_DIR = os.path.join(BASE_DIR, "cleaned_requests")


def get_leaf_subtasks(request_data, parent_path=""):
    """
    Recursively traverse the request structure and find all leaf subtasks.
    A leaf subtask is one with no children (empty subtasks array).
    
    Args:
        request_data: Dict representing the request or subtask
        parent_path: Path to current node for tracking hierarchy
    
    Returns:
        list: All leaf subtasks with their paths and complexity scores
    """
    leaves = []
    subtasks = request_data.get("subtasks", [])
    
    # If no subtasks, this is a leaf
    if not subtasks:
        leaf_info = {
            "path": parent_path,
            "input": request_data.get("input", ""),
            "complexity_score": request_data.get("complexity_score"),
            "eval_gen": request_data.get("eval_gen")
        }
        leaves.append(leaf_info)
        return leaves
    
    # Otherwise, recurse into each subtask
    for i, subtask in enumerate(subtasks):
        child_path = f"{parent_path}[{i}]" if parent_path else f"subtasks[{i}]"
        leaves.extend(get_leaf_subtasks(subtask, child_path))
    
    return leaves


def check_cleaned_requests(complexity_threshold=20):
    """
    Check all cleaned requests and identify leaf subtasks with complexity > threshold.
    
    Args:
        complexity_threshold: Minimum complexity score to report (default 20)
    
    Returns:
        dict: Statistics and findings
    """
    if not os.path.exists(CLEANED_DIR):
        print(f"Cleaned requests directory not found: {CLEANED_DIR}")
        return {}
    
    json_files = glob.glob(os.path.join(CLEANED_DIR, "*.json"))
    if not json_files:
        print(f"No JSON files found in {CLEANED_DIR}")
        return {}
    
    results = {
        "total_files": 0,
        "files_with_decomposition": 0,
        "total_leaves": 0,
        "leaves_above_threshold": 0,
        "files_analysis": []
    }
    
    print(f"Analyzing cleaned requests for leaf subtasks with complexity > {complexity_threshold}\n")
    print(f"{'='*80}")
    
    for request_file in sorted(json_files):
        try:
            with open(request_file, "r", encoding="utf-8") as f:
                request_data = json.load(f)
            
            results["total_files"] += 1
            filename = os.path.basename(request_file)
            
            # Get all leaves
            leaves = get_leaf_subtasks(request_data)
            
            # Filter for leaves with complexity > threshold
            high_complexity_leaves = [
                leaf for leaf in leaves 
                if leaf.get("complexity_score") is not None and leaf["complexity_score"] > complexity_threshold
            ]
            
            results["total_leaves"] += len(leaves)
            results["leaves_above_threshold"] += len(high_complexity_leaves)
            
            has_decomposition = len(request_data.get("subtasks", [])) > 0
            if has_decomposition:
                results["files_with_decomposition"] += 1
            
            # Report file analysis
            file_analysis = {
                "filename": filename,
                "root_complexity": request_data.get("complexity_score"),
                "has_decomposition": has_decomposition,
                "total_leaves": len(leaves),
                "high_complexity_leaves": len(high_complexity_leaves),
                "all_leaves": []
            }
            
            # Add all leaves with their details
            for leaf in leaves:
                leaf_detail = {
                    "path": leaf["path"],
                    "complexity_score": leaf["complexity_score"],
                    "input": leaf["input"][:80] + "..." if len(leaf["input"]) > 80 else leaf["input"],
                    "above_threshold": leaf["complexity_score"] > complexity_threshold if leaf["complexity_score"] is not None else False
                }
                file_analysis["all_leaves"].append(leaf_detail)
            
            results["files_analysis"].append(file_analysis)
            
            # Print summary for this file
            print(f"\nFile: {filename}")
            print(f"  Root complexity: {request_data.get('complexity_score')}")
            print(f"  Has decomposition: {has_decomposition}")
            print(f"  Total leaf subtasks: {len(leaves)}")
            print(f"  Leaves with complexity > {complexity_threshold}: {len(high_complexity_leaves)}")
            
            if high_complexity_leaves:
                print(f"  High complexity leaves:")
                for leaf in high_complexity_leaves:
                    print(f"    - {leaf['path']}: {leaf['complexity_score']} - {leaf['input'][:60]}...")
        
        except Exception as e:
            print(f"Error processing {os.path.basename(request_file)}: {e}")
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"\nSummary:")
    print(f"  Total files analyzed: {results['total_files']}")
    print(f"  Files with decomposition: {results['files_with_decomposition']}")
    print(f"  Total leaf subtasks found: {results['total_leaves']}")
    print(f"  Leaf subtasks with complexity > {complexity_threshold}: {results['leaves_above_threshold']}")
    
    if results['leaves_above_threshold'] > 0:
        percentage = (results['leaves_above_threshold'] / results['total_leaves'] * 100) if results['total_leaves'] > 0 else 0
        print(f"  Percentage: {percentage:.1f}%")
    
    print(f"{'='*80}")
    
    return results


if __name__ == "__main__":
    import sys
    
    threshold = 20
    if len(sys.argv) > 1:
        try:
            threshold = int(sys.argv[1])
        except ValueError:
            print(f"Invalid threshold: {sys.argv[1]}")
            print("Usage: python check_leaf_complexity.py [complexity_threshold]")
            sys.exit(1)
    
    results = check_cleaned_requests(complexity_threshold=threshold)
    
    # Export results to JSON for further analysis
    output_file = os.path.join(BASE_DIR, "leaf_complexity_report.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed report saved to: {output_file}")
