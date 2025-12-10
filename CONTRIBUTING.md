# Contributing to Kryten LLM

Thank you for considering contributing to Kryten LLM! This document provides guidelines for contributing to the project.

## Code of Conduct

Be respectful and considerate in all interactions. We aim to maintain a welcoming and inclusive community.

## How to Contribute

### Reporting Issues

- Check if the issue already exists in the issue tracker
- Provide a clear description of the problem
- Include steps to reproduce the issue
- Include relevant logs and error messages
- Specify your environment (OS, Python version, etc.)

### Suggesting Enhancements

- Open an issue to discuss the enhancement before implementing
- Explain the use case and benefits
- Consider backward compatibility

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests if applicable
5. Ensure all tests pass
6. Run linting and formatting tools
7. Commit your changes with clear messages
8. Push to your fork
9. Open a Pull Request

## Development Setup

1. Clone your fork:
```bash
git clone https://github.com/YOUR_USERNAME/kryten-llm.git
cd kryten-llm
```

2. Install dependencies:
```bash
poetry install
```

3. Create a config file:
```bash
cp config.example.json config.json
```

## Code Style

We use the following tools to maintain code quality:

- **Black** for code formatting
- **Ruff** for linting
- **MyPy** for type checking

Run these before committing:

```bash
# Format code
poetry run black .

# Lint code
poetry run ruff check .

# Fix auto-fixable issues
poetry run ruff check --fix .

# Type checking
poetry run mypy kryten_llm
```

## Testing

Run tests with pytest:

```bash
poetry run pytest
```

Run tests with coverage:

```bash
poetry run pytest --cov=kryten_llm --cov-report=term-missing
```

## Commit Messages

Follow these guidelines for commit messages:

- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit the first line to 72 characters
- Reference issues and pull requests when applicable

Prefix commit messages with a type:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks
- `ci:` - CI/CD changes

Example:
```
feat: add spam detection to chat message handler

Add basic spam detection that checks message frequency
and content patterns.

Fixes #123
```

## Branch Naming

Use descriptive branch names:

- `feature/description` - For new features
- `fix/description` - For bug fixes
- `docs/description` - For documentation
- `refactor/description` - For refactoring

## Pull Request Process

1. Update the README.md with details of changes if applicable
2. Update the CHANGELOG.md with your changes
3. Ensure CI checks pass
4. Request review from maintainers
5. Address review feedback
6. Squash commits if requested

## Questions?

Open an issue with the question label or reach out to the maintainers.

Thank you for contributing!
