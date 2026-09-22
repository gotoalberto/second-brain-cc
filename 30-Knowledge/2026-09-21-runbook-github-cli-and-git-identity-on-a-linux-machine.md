---
id: 2026-09-21-runbook-github-cli-and-git-identity-on-a-linux-machine
title: Runbook for the GitHub CLI, an account SSH key and signed commits on a Linux machine
type: howto
area: [harness]
projects: []
tags: [github, gh, git, ssh, commit-signing, linux, machines, runbook]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## What this fixes

A machine installed with [[2026-09-21-runbook-install-on-a-new-machine]] can push the vault and
nothing else. Three things are missing, and each fails quietly:

- The SSH key from the install is a **deploy key**, scoped to the vault repository. Against any
  other repository it is no credential at all: `ssh -T git@github.com` answers
  `Hi <owner>/<vault repo>!`, and cloning anything else fails.
- **No `gh`**, so no pull requests and no `gh api`.
- **No global git identity.** Commits take whatever the repository's local config says, or the
  system user's name, and go out under a name that is not yours.

Run everything below as the harness user, except the package steps.

## 1. Install gh from GitHub's repository, and pin it

Distribution packages of `gh` lag well behind. On some distributions an old `gh` is served
from an extra pocket at a higher apt priority than the official repository gets, so adding
the official repository alone changes nothing and apt says nothing. Pin it:

```sh
# as root
mkdir -p -m 755 /etc/apt/keyrings
wget -nv -O- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  > /etc/apt/keyrings/githubcli-archive-keyring.gpg
chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list
printf 'Package: gh\nPin: origin cli.github.com\nPin-Priority: 900\n' \
  > /etc/apt/preferences.d/github-cli
apt update && apt install -y gh
```

Check `apt-cache policy gh` before believing the install worked.

## 2. An account key next to the deploy key

Generate a second key; the deploy key stays where it is:

```sh
ssh-keygen -t ed25519 -N "" -C "<user>@<machine label>" -f ~/.ssh/id_ed25519_github
```

Register the public half twice on your GitHub account, once for authentication and once for
signing, from a machine whose `gh` is already authenticated (the token needs
`admin:public_key` and `admin:ssh_signing_key`):

```sh
gh ssh-key add key.pub --type authentication --title "<machine label>"
gh ssh-key add key.pub --type signing        --title "<machine label> signing"
```

GitHub refuses the same key as both a deploy key and an account key, which is why this is a new
key. Order the two in `~/.ssh/config`, account key first, so every repository works and the vault
keeps its fallback:

```
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_github
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

`ssh -T git@github.com` must now answer `Hi <your login>!`, not `Hi <owner>/<vault repo>!`. That
one word is the whole test.

## 3. Git identity and signing

```sh
git config --global user.name "<your name>"
git config --global user.email "<your commit email, or GitHub's noreply address>"
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519_github
git config --global gpg.ssh.allowedsignersfile ~/.ssh/allowed_signers
```

Turn `commit.gpgsign` on globally, or only for the repositories that require it with an
`includeIf` block, the same split you use on your other machines.

**On Linux `user.signingkey` is the path to the private key.** On a Mac whose SSH agent resolves
signing keys (a password manager's agent, for example) the setting often holds the literal public
key string. Copied to a Linux machine with no such agent, that value makes `git commit -S` fail
with `Couldn't get agent socket?`.

List your emails against both this machine's key and your other machines' signing keys in
`~/.ssh/allowed_signers`, so each machine can verify the others' commits.

## 4. Authenticate gh

Three ways, each with a cost:

- **A dedicated token for this machine** (a fine-grained or classic PAT, filed in the kdbx).
  Independent and revocable on its own; you mint it in a browser.
- **The device flow** (`gh auth login` on this machine). Uses the same OAuth app as your other
  machines, which can rotate their tokens and start a ping-pong between them.
- **Copying another machine's token** (`gh auth token | ssh <machine> gh auth login --with-token`,
  never through a transcript). Fastest, but it is one credential on two machines: the day `gh auth
  login` runs again on the source machine, this one loses access with no warning.

Then `gh config set git_protocol ssh`, and `chmod 600 ~/.config/gh/hosts.yml`: a headless machine
has no keyring, so `gh` writes the token there in plain text.

## Verify on GitHub

A command succeeding proves nothing here. Clone a repository fresh, make an empty signed commit
on a throwaway branch, push it, and ask GitHub what it thinks of the signature:

```sh
gh api repos/<owner>/<repo>/commits/$(git rev-parse HEAD) --jq '.commit.verification'
```

`{"verified": true, "reason": "valid"}` is the only pass. A good local signature
(`git log --format=%G?` printing `G`) only proves the key signed it, not that GitHub knows the
key. Delete the branch afterwards.

## Organisations with SAML SSO

For an organisation that enforces SAML single sign-on, cloning over SSH can still fail with
`The '<org>' organization has enabled or enforced SAML SSO ... grant this key access`, even with
everything above in place. `gh repo clone` fails the same way, because with `git_protocol ssh` it
shells out to the same blocked path. `gh api` and `gh repo list <org>` keep working, which is
misleading: the OAuth token is authorized for SSO, the SSH key is not.

Either authorize the SSH key for the organisation on GitHub, or clone over HTTPS through `gh`'s own
credential helper, which uses the authorized token:

```sh
git -c credential.helper='!gh auth git-credential' clone https://github.com/<org>/<repo>.git
```

## Accepting a repository invitation

An invitation to a private repository you have not accepted yet can be listed and accepted from
the CLI, with no browser:

```sh
gh api user/repository_invitations
gh api -X PATCH user/repository_invitations/<id>
```

## The root user

Leave root's git identity alone and give it no `gh`. The harness runs as its own user, and that
is the only identity that commits. A commit that shows up under root's name is a sign something
ran as the wrong user.

## Links

- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user]]
