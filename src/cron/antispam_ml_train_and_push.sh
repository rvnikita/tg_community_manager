#!/bin/bash
set -e

# Set the PYTHONPATH to the current working directory (project root)
export PYTHONPATH=$(pwd)

# --- Git initialization ---
# If .git does not exist, initialize the repository and set the remote.
if [ ! -d ".git" ]; then
    echo "No git repository found. Initializing..."
    git init
    # Use the REMOTE_REPO_URL environment variable to avoid hardcoding your repo URL.
    # REMOTE_REPO_URL should be of the form:
    #   https://github.com/username/repo.git
    git remote add origin "https://github.com/rvnikita/tg_community_manager.git"
    git checkout -b main
fi

# Attempt to pull remote changes (if any). Ignore errors if the remote branch does not exist.
echo "Pulling remote changes..."
git pull origin main || echo "No remote branch 'main' yet."

# --- Run Training ---
echo "Running spam classifier training..."
python ./src/cron/antispam_ml_optimized.py

# --- Check for changes and push ---
# Only check the ml_models folder for changes.
if git status --porcelain ml_models/ | grep .; then
    echo "Changes detected in ml_models/. Committing and pushing to GitHub..."
    
    # Stage only files in ml_models/
    git add ml_models/
    
    # Commit changes with a timestamp.
    git commit -m "Automated update of spam model on $(date --utc +'%Y-%m-%dT%H:%M:%SZ')"
    
    # Push to GitHub. The REMOTE_REPO_URL is already set, but we insert the token here.
    # We use the environment variable GITHUB_TOKEN to securely pass the token.
    # For example, if REMOTE_REPO_URL is "https://github.com/username/repo.git", this command becomes:
    #   git push https://$GITHUB_TOKEN@github.com/username/repo.git main
    git push https://$GITHUB_TOKEN@$(echo "$REMOTE_REPO_URL" | sed 's_https://__') main
    echo "Push complete."
else
    echo "No changes detected in ml_models/; nothing to commit."
fi
