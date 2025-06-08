
# Git Cheatsheet

## Configuration

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
git config --global core.editor "code --wait"  # Set VS Code as Git editor
git config --global alias.st status            # Create alias for status
git config --list                              # Show all global configs
```

## Repository Setup

```bash
git init                            # Initialize a new repo
git clone <url>                     # Clone a remote repo
git remote -v                       # View remotes
git remote add origin <url>        # Add a new remote
```

## Basic Workflow

```bash
git status                         # Check current state
git add <file>                     # Stage a file
git add .                          # Stage all changes
git commit -m "Message"            # Commit changes
git commit -am "Message"           # Add & commit tracked files
git push                           # Push to remote
git pull                           # Pull latest changes
```

## Branching

```bash
git branch                         # See local branches only
git branch -a                      # See all branch (local + remote)
git branch -r                      # See remote branches
git branch <name>                  # Create a new branch
git checkout <name>                # Switch to branch
git checkout -b <name>             # Create and switch
git merge <branch>                 # Merge a branch
git branch -d <name>               # Delete local branch
git push origin --delete <name>    # Delete remote branch
```

## Stashing

```bash
git stash                          # Save changes
git stash -u                       # Save changes (untracked too)
git stash pop                      # Apply and remove latest stash
git stash apply                    # Apply without removing
git stash list                     # List all stashes
git stash drop stash@{n}          # Drop a specific stash
```

## Inspection

```bash
git log                            # Commit history
git log --oneline --graph --all    # Visual branch structure
git diff                           # Unstaged vs working
git diff --cached                  # Staged vs last commit
git show <commit>                  # Show commit details
git blame <file>                   # Show line-by-line author
```

## Viewing Changes with

```bash
git diff                                # Show unstaged changes (working directory vs index)
git diff <file>                         # Show unstaged changes in a specific file
git diff --cached                       # Show staged changes (index vs last commit)
git diff HEAD                           # Show all changes (working directory vs last commit)
git diff HEAD <file>                    # Show all changes for a specific file

git diff --stat                         # Show summary of changes (file list, insertions/deletions)
git diff --color-words                  # Highlight changes word-by-word (instead of line-by-line)
git diff --name-only                    # Show only the names of changed files
git diff --name-status                  # Show file names and status (Added/Modified/Deleted)

# Show changes between any two commits or branches
git diff <commit1> <commit2>
git diff <branch1>..<branch2>
```

## Undo & Reset

```bash
git restore <file>                 # Discard working dir changes
git restore --staged <file>        # Unstage file
git reset <commit>                 # Reset to commit (soft/mixed/hard)
git reset --hard HEAD~1            # Delete last commit
git clean -fd                      # Remove untracked files/dirs
```

## Tags

```bash
git tag                     # List tags
git tag v1.0                # Create a lightweight tag
git tag -a v1.0 -m "msg"    # Annotated tag
git show v1.0               # Show tag details
git push origin v1.0        # Push a single tag
git push origin --tags      # Push all tags
git tag -d v1.0             # Delete local tag
git push --delete origin v1.0 # Delete remote tag
```

## Cherry-pick

```bash
git cherry-pick <commit>          # Apply a specific commit
git cherry-pick <a>^..<b>         # Range of commits
```

## Rebase

```bash
git rebase <branch>                # Replay commits on top
git rebase -i HEAD~n               # Interactive rebase (edit, squash)
git rebase --abort                 # Cancel rebase
git rebase --continue              # Continue rebase
```

## Rewriting History

```bash
git commit --amend                 # Edit last commit
git rebase -i HEAD~n               # Reorder/squash commits
git reset --hard <commit>         # Rewind to previous commit
```

## Collaboration

```bash
git fetch                          # Fetch from origin
git pull --rebase                  # Pull with rebase
git push -u origin <branch>        # Push and set upstream
```

## Signed Commits

```bash
git config --global user.signingkey <key-id>
git config --global commit.gpgsign true
git commit -S -m "Signed commit"
```

##️ Changing Commit Author

```bash
git commit --amend --author="New Name <new@example.com>"
```

---

## Search and Grep

```bash
git grep "text"                    # Search tracked files
git log -S"term"                   # Search changes adding/removing term
```

## Cleanup

```bash
git gc                             # Garbage collect
git prune                          # Remove unreachable objects
git reflog                         # Show history of HEAD
```

## Submodules

```bash
git submodule add <repo> [path]
git submodule update --init --recursive
git submodule foreach git pull origin main
```

## History Rewriting with BFG

```bash
bfg --delete-files id_rsa
bfg --delete-folders .idea
bfg --replace-text passwords.txt
```

---

## Tips & Best Practices

- Use `git status` and `git log` often.
- Use branches for features and fixes.
- Squash commits before merging to main.
- Always pull before pushing to avoid conflicts.

## References

- [Pro Git Book](https://git-scm.com/book/en/v2)
- [Git Documentation](https://git-scm.com/docs)
- [BFG Repo Cleaner](https://rtyley.github.io/bfg-repo-cleaner/)
