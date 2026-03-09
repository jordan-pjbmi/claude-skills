"""Git worktree creation, commit helpers, and merge operations."""

import subprocess
from pathlib import Path

from db import get_connection, now_iso


def run_git(args, cwd=None):
    """Run a git command, return (success, stdout, stderr)."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def worktree_create(project_root, sprint_id, repo_path=None):
    """Create a git worktree for a sprint.

    1. Creates branch sprint/<id>-<slug> from current main
    2. Creates worktree at {project_root}/.worktrees/sprint-<id>/
    3. Records worktree path in sprints table
    """
    conn = get_connection(project_root)
    sprint = conn.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,)).fetchone()
    if not sprint:
        conn.close()
        return False, "Sprint not found."

    slug = sprint["name"].lower().replace(" ", "-")
    branch = f"sprint/{sprint_id}-{slug}"
    worktree_dir = project_root / ".worktrees" / f"sprint-{sprint_id}"

    # Determine which repo to create the worktree in
    git_dir = Path(repo_path) if repo_path else project_root
    # Find the actual git repo root
    ok, git_root, _ = run_git(["rev-parse", "--show-toplevel"], cwd=str(git_dir))
    if not ok:
        conn.close()
        return False, f"Not a git repository: {git_dir}"
    git_root = Path(git_root)

    # Get main branch name
    from db import load_config
    config = load_config(project_root)
    main_branch = config.get("main_branch", "main")

    # Create branch from main
    ok, _, err = run_git(["branch", branch, main_branch], cwd=str(git_root))
    if not ok and "already exists" not in err:
        conn.close()
        return False, f"Failed to create branch: {err}"

    # Create worktree
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    ok, _, err = run_git(["worktree", "add", str(worktree_dir), branch], cwd=str(git_root))
    if not ok:
        conn.close()
        return False, f"Failed to create worktree: {err}"

    # Update sprint record
    ts = now_iso()
    conn.execute(
        "UPDATE sprints SET branch_name=?, worktree_path=?, updated_at=? WHERE id=?",
        (branch, str(worktree_dir), ts, sprint_id),
    )
    conn.commit()
    conn.close()
    return True, f"Worktree created at {worktree_dir} on branch {branch}"


def worktree_destroy(project_root, sprint_id):
    """Remove a worktree for a sprint."""
    conn = get_connection(project_root)
    sprint = conn.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,)).fetchone()
    if not sprint:
        conn.close()
        return False, "Sprint not found."

    worktree_path = sprint["worktree_path"]
    if not worktree_path:
        conn.close()
        return False, "No worktree path recorded for this sprint."

    # Find git root — try from project root
    ok, git_root, _ = run_git(["rev-parse", "--show-toplevel"], cwd=str(project_root))
    if not ok:
        conn.close()
        return False, "Could not find git repository."

    # Remove worktree
    ok, _, err = run_git(["worktree", "remove", worktree_path, "--force"], cwd=git_root)
    if not ok:
        conn.close()
        return False, f"Failed to remove worktree: {err}"

    # Clean up branch if desired
    branch = sprint["branch_name"]
    if branch:
        run_git(["branch", "-d", branch], cwd=git_root)

    # Update sprint record
    ts = now_iso()
    conn.execute(
        "UPDATE sprints SET worktree_path='', updated_at=? WHERE id=?",
        (ts, sprint_id),
    )
    conn.commit()
    conn.close()
    return True, f"Worktree removed: {worktree_path}"


def worktree_list(project_root):
    """List active worktrees from sprint records."""
    conn = get_connection(project_root)
    sprints = conn.execute(
        "SELECT id, name, branch_name, worktree_path FROM sprints WHERE worktree_path != '' AND worktree_path IS NOT NULL"
    ).fetchall()
    conn.close()

    if not sprints:
        return "No active worktrees."

    lines = []
    for s in sprints:
        exists = Path(s["worktree_path"]).exists()
        status = "" if exists else " (MISSING)"
        lines.append(f"  Sprint {s['id']} ({s['name']}): {s['worktree_path']} [{s['branch_name']}]{status}")
    return "\n".join(lines)


def merge_sprint(project_root, sprint_id, strategy="merge"):
    """Merge a sprint branch into main.

    strategy: 'merge' for merge commit, 'rebase' for rebase
    """
    conn = get_connection(project_root)
    sprint = conn.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,)).fetchone()
    if not sprint:
        conn.close()
        return False, "Sprint not found."

    branch = sprint["branch_name"]
    if not branch:
        conn.close()
        return False, "No branch recorded for this sprint."

    from db import load_config
    config = load_config(project_root)
    main_branch = config.get("main_branch", "main")

    ok, git_root, _ = run_git(["rev-parse", "--show-toplevel"], cwd=str(project_root))
    if not ok:
        conn.close()
        return False, "Could not find git repository."

    # Checkout main
    ok, _, err = run_git(["checkout", main_branch], cwd=git_root)
    if not ok:
        conn.close()
        return False, f"Failed to checkout {main_branch}: {err}"

    if strategy == "rebase":
        ok, _, err = run_git(["rebase", branch], cwd=git_root)
    else:
        ok, _, err = run_git(["merge", branch, "--no-ff", "-m", f"Merge sprint {sprint['name']}"], cwd=git_root)

    if not ok:
        conn.close()
        return False, f"Merge failed: {err}"

    conn.close()
    return True, f"Sprint branch {branch} merged into {main_branch}"
