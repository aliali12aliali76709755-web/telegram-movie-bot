import subprocess
import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def get_github_token():
    p = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', capture_output=True, text=True)
    token = None
    for line in p.stdout.splitlines():
        if line.startswith('password='):
            token = line.split('=', 1)[1]
            break
    return token

def create_github_repo(token, repo_name="telegram-movie-bot"):
    url = "https://api.github.com/user/repos"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Antigravity-Agent"
    }
    payload = {
        "name": repo_name,
        "description": "Telegram Movie & Series Bot with auto-transfer and high-speed streaming",
        "private": True
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            print(f"Repository created successfully: {data['html_url']}")
            return data['clone_url']
    except urllib.error.HTTPError as e:
        if e.code == 422:
            print(f"Repository '{repo_name}' already exists.")
            return f"https://github.com/aliali12aliali76709755-web/{repo_name}.git"
        else:
            print(f"Error creating repo: {e}")
            return None

if __name__ == "__main__":
    t = get_github_token()
    if not t:
        print("No GitHub token found!")
    else:
        clone_url = create_github_repo(t)
        print("Repo Clone URL:", clone_url)
