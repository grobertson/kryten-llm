#!/bin/bash
# Start script for kryten-llm service

set -e

check_venv() {
	local path="$1"

	if [[ ! -d "$path" ]]; then
		return 1
	fi

	if [[ ! -f "$path/pyvenv.cfg" ]]; then
		return 1
	fi

	if [[ ! -f "$path/bin/python" ]] || [[ ! -f "$path/bin/pip" ]]; then
		return 1
	fi

	"$path/bin/python" -c "import sys" >/dev/null 2>&1
}

create_venv() {
	local path="$1"

	if command -v uv >/dev/null 2>&1; then
		uv venv "$path"
	else
		python3 -m venv "$path"
	fi
}

# Clear PYTHONPATH to avoid conflicts
export PYTHONPATH=""

# Change to script directory
cd "$(dirname "$0")"

# Ensure .venv is usable; recreate it if pyvenv metadata is missing/corrupted.
if ! check_venv ".venv"; then
	if [[ -d ".venv" ]]; then
		if ! rm -rf ".venv"; then
			echo "Could not remove corrupted .venv. Close processes using this environment and try again." >&2
			exit 1
		fi
	fi
	create_venv ".venv"

	if ! check_venv ".venv"; then
		echo "Failed to create a valid virtual environment at .venv" >&2
		exit 1
	fi
fi

# Start the service
uv run kryten-llm --config config.json
