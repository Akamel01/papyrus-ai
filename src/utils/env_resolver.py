"""
SME Research Assistant - Environment Variable Resolver

Resolves ${VAR_NAME} references in configuration files to their
corresponding environment variable values at runtime.

This enables secure credential management where secrets are stored
in .env files (gitignored) rather than in config YAML files.
"""

import os
import re
from typing import Any, Dict, List, Union


def resolve_env_vars(value: Any) -> Any:
    """
    Recursively replace ${VAR_NAME} patterns with os.environ['VAR_NAME'].

    Supports optional default values with syntax: ${VAR_NAME:-default}

    Args:
        value: Configuration value (string, dict, list, or primitive)

    Returns:
        Value with all ${VAR} references resolved

    Raises:
        EnvironmentError: If required env var is not set and no default provided

    Examples:
        >>> os.environ['API_KEY'] = 'secret123'
        >>> resolve_env_vars('${API_KEY}')
        'secret123'
        >>> resolve_env_vars({'key': '${API_KEY}'})
        {'key': 'secret123'}
        >>> resolve_env_vars('${MISSING:-fallback}')
        'fallback'
    """
    if isinstance(value, str):
        # Pattern matches ${VAR} or ${VAR:-default}
        pattern = r'\$\{(\w+)(?::-([^}]*))?\}'

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            default_value = match.group(2)  # None if no default specified

            env_val = os.environ.get(var_name)

            if env_val is not None:
                return env_val
            elif default_value is not None:
                return default_value
            else:
                raise EnvironmentError(
                    f"Required environment variable '{var_name}' is not set. "
                    f"Run scripts/setup.sh to configure your environment, "
                    f"or copy .env.example to .env and fill in your values."
                )

        return re.sub(pattern, replacer, value)

    elif isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [resolve_env_vars(item) for item in value]

    # Return primitives (int, float, bool, None) unchanged
    return value


def mask_secrets(config: Dict[str, Any], secret_keys: set = None) -> Dict[str, Any]:
    """
    Create a copy of config with secret values masked for safe logging.

    Args:
        config: Configuration dictionary
        secret_keys: Set of key names to mask (default: common secret patterns)

    Returns:
        Config copy with secrets replaced by '***REDACTED***'
    """
    if secret_keys is None:
        secret_keys = {
            'api_key', 'apikey', 'api_secret', 'secret', 'password',
            'token', 'jwt_secret', 'private_key', 'credential'
        }

    def _mask(obj: Any, parent_key: str = '') -> Any:
        if isinstance(obj, dict):
            return {
                k: _mask(v, k) for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [_mask(item, parent_key) for item in obj]
        elif isinstance(obj, str):
            # Mask if parent key suggests this is a secret
            if any(sk in parent_key.lower() for sk in secret_keys):
                return '***REDACTED***'
            return obj
        return obj

    return _mask(config)
