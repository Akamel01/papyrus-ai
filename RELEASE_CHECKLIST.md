# Release Checklist

**Last Updated: March 2026**

This document provides a comprehensive pre-release verification checklist to ensure all components are properly tested and documented before releasing a new version.

---

## 1. Pre-Release Verification

- [ ] All Phase 1-5 implementation tasks completed
- [ ] No critical security vulnerabilities open
- [ ] All tests passing
- [ ] Documentation up to date
- [ ] Code review completed for all changes
- [ ] No TODO/FIXME items blocking release

---

## 2. Security Verification

### Data Isolation
- [ ] User data isolation tested (User A cannot access User B's data)
- [ ] User deletion isolation tested (deleted user's data is properly removed)
- [ ] Session isolation verified between users

### Authentication & Authorization
- [ ] Rate limiting functional
- [ ] Login lockout functional after failed attempts
- [ ] JWT tokens expire correctly
- [ ] Refresh token rotation working
- [ ] Password reset flow secure

### Data Protection
- [ ] API keys encrypted at rest
- [ ] Sensitive data encrypted in database
- [ ] No secrets in config files
- [ ] .env permissions are 600 (owner read/write only)

### Network Security
- [ ] CORS properly configured
- [ ] Security headers present (X-Frame-Options, X-Content-Type-Options, etc.)
- [ ] HTTPS enforced in production
- [ ] No sensitive data in URLs or logs

---

## 3. Functionality Verification

### User Management
- [ ] User registration works
- [ ] User login works
- [ ] Password change works
- [ ] Password reset works
- [ ] User profile update works
- [ ] User deletion works

### Core Features
- [ ] API key storage works
- [ ] API key retrieval works
- [ ] Paper upload works
- [ ] Paper parsing succeeds
- [ ] Search returns results
- [ ] Search filters work correctly

### LLM Integration
- [ ] LLM generation works
- [ ] Citations properly formatted
- [ ] Response streaming works (if applicable)
- [ ] Error handling for LLM failures

---

## 4. Infrastructure Verification

### Docker
- [ ] All Docker containers start successfully
- [ ] Containers restart on failure
- [ ] Health checks pass for all services
- [ ] Docker Compose up/down works cleanly

### Networking
- [ ] Cloudflare tunnel connects (if enabled)
- [ ] Internal service communication works
- [ ] External API endpoints accessible

### Backup & Recovery
- [ ] Backup script works
- [ ] Restore script works
- [ ] Backup files are created correctly
- [ ] Restore from backup verified

---

## 5. Performance Verification

### Load Testing
- [ ] 5 concurrent users tested
- [ ] Response times acceptable:
  - [ ] Search: < 5 seconds
  - [ ] LLM generation: < 30 seconds
  - [ ] Page loads: < 2 seconds
  - [ ] API responses: < 1 second

### Resource Usage
- [ ] No memory leaks observed
- [ ] CPU usage within acceptable limits
- [ ] Disk space adequate (minimum 20% free)
- [ ] Database connection pool sized correctly

---

## 6. Documentation Verification

- [ ] ARCHITECTURE.md accurate and reflects current system
- [ ] SECURITY.md accurate and covers all security measures
- [ ] DEPLOYMENT_GUIDE.md tested by non-technical user
- [ ] TROUBLESHOOTING.md covers common issues
- [ ] API_REFERENCE.md complete with all endpoints
- [ ] README.md up to date
- [ ] Inline code comments accurate
- [ ] Environment variable documentation complete

---

## 7. Release Steps

Follow these steps in order when creating a new release:

### Step 1: Version Update
1. Update version number in `package.json` (if applicable)
2. Update version number in `pyproject.toml` (if applicable)
3. Update version number in `docker-compose.yml` image tags
4. Update version in any configuration files

### Step 2: Documentation Updates
1. Update "Last Updated" dates in all documentation files:
   - ARCHITECTURE.md
   - SECURITY.md
   - DEPLOYMENT_GUIDE.md
   - TROUBLESHOOTING.md
   - API_REFERENCE.md
   - RELEASE_CHECKLIST.md
2. Review and update any outdated information

### Step 3: Generate Changelog
1. Review all commits since last release
2. Categorize changes:
   - **Added**: New features
   - **Changed**: Changes to existing functionality
   - **Deprecated**: Features to be removed in future
   - **Removed**: Removed features
   - **Fixed**: Bug fixes
   - **Security**: Security-related changes
3. Update CHANGELOG.md with new version section

### Step 4: Final Verification
1. Run full test suite
2. Perform smoke test of critical paths
3. Verify all checklist items above are complete

### Step 5: Create Git Tag
```bash
# Ensure you're on the main branch with latest changes
git checkout main
git pull origin main

# Create annotated tag
git tag -a v1.x.x -m "Release version 1.x.x"

# Push tag to remote
git push origin v1.x.x
```

### Step 6: Create Release
1. Create GitHub/GitLab release from tag
2. Include changelog entries in release notes
3. Attach any release artifacts (if applicable)
4. Mark as pre-release if applicable

### Step 7: Post-Release
1. Announce release to stakeholders
2. Monitor for immediate issues
3. Update any deployment environments
4. Archive release documentation

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Developer | | | |
| Security Review | | | |
| QA | | | |
| Release Manager | | | |

---

## Notes

_Add any release-specific notes or known issues here:_

-
-
-
