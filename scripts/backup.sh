#!/bin/bash
# SME Research Assistant - Comprehensive Backup Script
# Creates timestamped backups of databases, configs, and pipeline state.
#
# Usage:
#   bash scripts/backup.sh                    # Standard backup
#   bash scripts/backup.sh --include-qdrant   # Include Qdrant vector data
#   bash scripts/backup.sh --keep 14          # Keep last 14 backups
#   bash scripts/backup.sh --output /path     # Custom output directory
#
# Exit codes:
#   0 - Success
#   1 - General error
#   2 - Missing required files
#   3 - Compression failed
#   4 - Insufficient disk space

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "$PROJECT_ROOT"

# ── Color Definitions ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── Helper Functions ──
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }
step()    { echo -e "\n${BOLD}${CYAN}>> $1${NC}"; }

# ── Default Configuration ──
BACKUP_ROOT="${PROJECT_ROOT}/backups"
INCLUDE_QDRANT=false
KEEP_BACKUPS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
START_TIME=$(date +%s)

# ── Parse Arguments ──
while [[ $# -gt 0 ]]; do
    case $1 in
        --include-qdrant)
            INCLUDE_QDRANT=true
            shift
            ;;
        --keep)
            KEEP_BACKUPS="$2"
            shift 2
            ;;
        --output)
            BACKUP_ROOT="$2"
            BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
            shift 2
            ;;
        -h|--help)
            echo "SME Research Assistant - Backup Script"
            echo ""
            echo "Usage: bash scripts/backup.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --include-qdrant    Include Qdrant vector database (can be large)"
            echo "  --keep N            Keep last N backups (default: 7)"
            echo "  --output PATH       Custom backup output directory"
            echo "  -h, --help          Show this help message"
            echo ""
            echo "Backed up items:"
            echo "  - SQLite databases (data/*.db)"
            echo "  - Configuration files (config/*.yaml, .env)"
            echo "  - Pipeline state (data/pipeline_state.json)"
            echo "  - BM25 index (data/bm25_index_tantivy/)"
            echo "  - Papers/PDFs (DataBase/Papers/)"
            echo "  - Qdrant data (optional, with --include-qdrant)"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# ── Cleanup on Error ──
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        error "Backup failed with exit code $exit_code"
        # Clean up partial backup
        if [ -d "$BACKUP_DIR" ]; then
            warn "Cleaning up partial backup at $BACKUP_DIR"
            rm -rf "$BACKUP_DIR"
        fi
        if [ -f "${BACKUP_DIR}.tar.gz" ]; then
            rm -f "${BACKUP_DIR}.tar.gz"
        fi
    fi
    exit $exit_code
}

trap cleanup EXIT

# ══════════════════════════════════════════════════════════════════════
# Header
# ══════════════════════════════════════════════════════════════════════
echo -e "${BOLD}==========================================="
echo "  SME Research Assistant - Backup"
echo -e "===========================================${NC}"
echo ""
info "Timestamp: ${TIMESTAMP}"
info "Backup directory: ${BACKUP_DIR}"
info "Include Qdrant: ${INCLUDE_QDRANT}"
info "Keep last ${KEEP_BACKUPS} backups"
echo ""

# ══════════════════════════════════════════════════════════════════════
# STEP 1: Pre-flight Checks
# ══════════════════════════════════════════════════════════════════════
step "Pre-flight Checks"

# Check for required directories
if [ ! -d "data" ]; then
    error "Data directory not found at ${PROJECT_ROOT}/data"
    exit 2
fi
success "Data directory exists"

if [ ! -d "config" ]; then
    warn "Config directory not found - will skip config backup"
fi

# Check available disk space (estimate needed space)
ESTIMATED_SIZE_MB=500
if [ "$INCLUDE_QDRANT" = true ]; then
    # Qdrant can be large, estimate based on existing data
    if [ -d "qdrant_storage" ]; then
        QDRANT_SIZE=$(du -sm "qdrant_storage" 2>/dev/null | cut -f1 || echo "0")
        ESTIMATED_SIZE_MB=$((ESTIMATED_SIZE_MB + QDRANT_SIZE))
    fi
fi

# Check disk space if df is available
if command -v df &> /dev/null; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        AVAILABLE_MB=$(df -m . | awk 'NR==2 {print $4}')
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        # Windows Git Bash
        AVAILABLE_MB=$(df -m . 2>/dev/null | awk 'NR==2 {print $4}' || echo "unknown")
    else
        AVAILABLE_MB=$(df -BM . 2>/dev/null | awk 'NR==2 {gsub(/M/,""); print $4}' || echo "unknown")
    fi

    if [ "$AVAILABLE_MB" != "unknown" ] && [ -n "$AVAILABLE_MB" ]; then
        if [ "$AVAILABLE_MB" -lt "$ESTIMATED_SIZE_MB" ]; then
            error "Insufficient disk space: ${AVAILABLE_MB}MB available, ~${ESTIMATED_SIZE_MB}MB needed"
            exit 4
        fi
        success "Disk space: ${AVAILABLE_MB}MB available (~${ESTIMATED_SIZE_MB}MB needed)"
    fi
fi

# Create backup directory
mkdir -p "$BACKUP_DIR"
success "Created backup directory"

# ══════════════════════════════════════════════════════════════════════
# STEP 2: Initialize Manifest
# ══════════════════════════════════════════════════════════════════════
step "Initializing Backup Manifest"

MANIFEST_FILE="${BACKUP_DIR}/manifest.json"
BACKED_UP_FILES=()
BACKUP_STATS=()

# Get git info if available
GIT_COMMIT=""
GIT_BRANCH=""
if command -v git &> /dev/null && [ -d ".git" ]; then
    GIT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    GIT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
fi

# Start manifest
cat > "$MANIFEST_FILE" << EOF
{
  "version": "1.0",
  "timestamp": "${TIMESTAMP}",
  "created_at": "$(date -Iseconds 2>/dev/null || date)",
  "hostname": "$(hostname)",
  "include_qdrant": ${INCLUDE_QDRANT},
  "git_commit": "${GIT_COMMIT}",
  "git_branch": "${GIT_BRANCH}",
  "files": [],
  "stats": {}
}
EOF
success "Manifest initialized"

# ══════════════════════════════════════════════════════════════════════
# STEP 3: Backup Databases
# ══════════════════════════════════════════════════════════════════════
step "Backing Up Databases"

mkdir -p "${BACKUP_DIR}/databases"

# Database files to back up
DB_FILES=("data/auth.db" "data/sme.db" "data/chat_history.db" "data/papers.db")
DB_COUNT=0

for db_file in "${DB_FILES[@]}"; do
    if [ -f "$db_file" ]; then
        db_name=$(basename "$db_file")

        # Use sqlite3 .backup if available for consistency, otherwise copy
        if command -v sqlite3 &> /dev/null; then
            # Create a safe backup using SQLite backup command
            sqlite3 "$db_file" ".backup '${BACKUP_DIR}/databases/${db_name}'" 2>/dev/null || \
                cp "$db_file" "${BACKUP_DIR}/databases/${db_name}"
        else
            cp "$db_file" "${BACKUP_DIR}/databases/${db_name}"
        fi

        DB_SIZE=$(du -h "${BACKUP_DIR}/databases/${db_name}" 2>/dev/null | cut -f1 || echo "unknown")
        success "Backed up ${db_name} (${DB_SIZE})"
        BACKED_UP_FILES+=("databases/${db_name}")
        DB_COUNT=$((DB_COUNT + 1))
    else
        warn "Database not found: $db_file (skipping)"
    fi
done

info "Backed up ${DB_COUNT} database(s)"

# ══════════════════════════════════════════════════════════════════════
# STEP 4: Backup Configuration Files
# ══════════════════════════════════════════════════════════════════════
step "Backing Up Configuration Files"

mkdir -p "${BACKUP_DIR}/config"
CONFIG_COUNT=0

# Backup YAML configs
if [ -d "config" ]; then
    for config_file in config/*.yaml config/*.yml 2>/dev/null; do
        if [ -f "$config_file" ]; then
            cp "$config_file" "${BACKUP_DIR}/config/"
            config_name=$(basename "$config_file")
            success "Backed up ${config_name}"
            BACKED_UP_FILES+=("config/${config_name}")
            CONFIG_COUNT=$((CONFIG_COUNT + 1))
        fi
    done
fi

# Backup .env file (sensitive - will note in manifest)
if [ -f ".env" ]; then
    cp ".env" "${BACKUP_DIR}/config/.env"
    success "Backed up .env"
    BACKED_UP_FILES+=("config/.env")
    CONFIG_COUNT=$((CONFIG_COUNT + 1))
fi

# Backup .env.example if exists
if [ -f ".env.example" ]; then
    cp ".env.example" "${BACKUP_DIR}/config/.env.example"
    BACKED_UP_FILES+=("config/.env.example")
fi

info "Backed up ${CONFIG_COUNT} configuration file(s)"

# ══════════════════════════════════════════════════════════════════════
# STEP 5: Backup Pipeline State
# ══════════════════════════════════════════════════════════════════════
step "Backing Up Pipeline State"

mkdir -p "${BACKUP_DIR}/state"
STATE_COUNT=0

# Pipeline state files
STATE_FILES=(
    "data/pipeline_state.json"
    "data/ingestion_state.json"
    "data/pipeline_stats.json"
    "data/pipeline_metrics.json"
    "data/discovery_coverage.json"
    "data/dashboard_users.json"
)

for state_file in "${STATE_FILES[@]}"; do
    if [ -f "$state_file" ]; then
        state_name=$(basename "$state_file")
        cp "$state_file" "${BACKUP_DIR}/state/${state_name}"
        success "Backed up ${state_name}"
        BACKED_UP_FILES+=("state/${state_name}")
        STATE_COUNT=$((STATE_COUNT + 1))
    fi
done

info "Backed up ${STATE_COUNT} state file(s)"

# ══════════════════════════════════════════════════════════════════════
# STEP 6: Backup BM25 Index
# ══════════════════════════════════════════════════════════════════════
step "Backing Up BM25 Index"

BM25_DIR="data/bm25_index_tantivy"
if [ -d "$BM25_DIR" ]; then
    mkdir -p "${BACKUP_DIR}/bm25_index"
    cp -r "$BM25_DIR"/* "${BACKUP_DIR}/bm25_index/" 2>/dev/null || true
    BM25_SIZE=$(du -sh "${BACKUP_DIR}/bm25_index" 2>/dev/null | cut -f1 || echo "unknown")
    success "Backed up BM25 index (${BM25_SIZE})"
    BACKED_UP_FILES+=("bm25_index/")
else
    warn "BM25 index not found at ${BM25_DIR} (skipping)"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 7: Backup Papers Directory (PDF files)
# ══════════════════════════════════════════════════════════════════════
step "Backing Up Papers Directory"

PAPERS_DIR="DataBase/Papers"
if [ -d "$PAPERS_DIR" ]; then
    # Check if directory has content
    PAPERS_COUNT=$(find "$PAPERS_DIR" -type f -name "*.pdf" 2>/dev/null | wc -l)

    if [ "$PAPERS_COUNT" -gt 0 ]; then
        info "Found ${PAPERS_COUNT} PDF files to backup..."
        mkdir -p "${BACKUP_DIR}/papers"

        # Copy all PDF files preserving directory structure
        cp -r "$PAPERS_DIR"/* "${BACKUP_DIR}/papers/" 2>/dev/null || true
        PAPERS_SIZE=$(du -sh "${BACKUP_DIR}/papers" 2>/dev/null | cut -f1 || echo "unknown")
        success "Backed up Papers directory (${PAPERS_SIZE}, ${PAPERS_COUNT} files)"
        BACKED_UP_FILES+=("papers/")
    else
        warn "Papers directory exists but contains no PDF files"
    fi
else
    # Also check alternative locations
    ALT_PAPERS_DIR="DataBase"
    if [ -d "$ALT_PAPERS_DIR" ]; then
        PAPERS_COUNT=$(find "$ALT_PAPERS_DIR" -type f -name "*.pdf" 2>/dev/null | wc -l)
        if [ "$PAPERS_COUNT" -gt 0 ]; then
            info "Found ${PAPERS_COUNT} PDF files in DataBase/ directory..."
            mkdir -p "${BACKUP_DIR}/papers"

            # Copy entire DataBase directory structure
            cp -r "$ALT_PAPERS_DIR"/* "${BACKUP_DIR}/papers/" 2>/dev/null || true
            PAPERS_SIZE=$(du -sh "${BACKUP_DIR}/papers" 2>/dev/null | cut -f1 || echo "unknown")
            success "Backed up DataBase directory (${PAPERS_SIZE}, ${PAPERS_COUNT} files)"
            BACKED_UP_FILES+=("papers/")
        else
            warn "DataBase directory exists but contains no PDF files"
        fi
    else
        warn "Papers directory not found at ${PAPERS_DIR} or ${ALT_PAPERS_DIR}"
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 8: Backup Qdrant (Optional)
# ══════════════════════════════════════════════════════════════════════
if [ "$INCLUDE_QDRANT" = true ]; then
    step "Backing Up Qdrant Vector Database"

    QDRANT_DIR="qdrant_storage"
    if [ -d "$QDRANT_DIR" ]; then
        info "This may take a while for large vector databases..."
        mkdir -p "${BACKUP_DIR}/qdrant"

        # Copy Qdrant storage
        cp -r "$QDRANT_DIR"/* "${BACKUP_DIR}/qdrant/" 2>/dev/null || true
        QDRANT_SIZE=$(du -sh "${BACKUP_DIR}/qdrant" 2>/dev/null | cut -f1 || echo "unknown")
        success "Backed up Qdrant data (${QDRANT_SIZE})"
        BACKED_UP_FILES+=("qdrant/")
    else
        warn "Qdrant storage not found at ${QDRANT_DIR}"

        # Try Docker volume
        if docker volume inspect sme_qdrant_data &> /dev/null 2>&1; then
            info "Attempting to backup Qdrant from Docker volume..."
            docker run --rm \
                -v sme_qdrant_data:/source:ro \
                -v "${BACKUP_DIR}/qdrant":/backup \
                alpine sh -c "cp -r /source/* /backup/" 2>/dev/null || warn "Could not backup Qdrant Docker volume"

            if [ -d "${BACKUP_DIR}/qdrant" ] && [ "$(ls -A ${BACKUP_DIR}/qdrant 2>/dev/null)" ]; then
                QDRANT_SIZE=$(du -sh "${BACKUP_DIR}/qdrant" 2>/dev/null | cut -f1 || echo "unknown")
                success "Backed up Qdrant from Docker volume (${QDRANT_SIZE})"
                BACKED_UP_FILES+=("qdrant/")
            fi
        fi
    fi
else
    info "Skipping Qdrant backup (use --include-qdrant to include)"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 8: Finalize Manifest
# ══════════════════════════════════════════════════════════════════════
step "Finalizing Manifest"

# Calculate backup size
BACKUP_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo "unknown")

# Get file count
FILE_COUNT=${#BACKED_UP_FILES[@]}

# Build files JSON array
FILES_JSON="["
for i in "${!BACKED_UP_FILES[@]}"; do
    FILES_JSON+="\"${BACKED_UP_FILES[$i]}\""
    if [ $i -lt $((FILE_COUNT - 1)) ]; then
        FILES_JSON+=","
    fi
done
FILES_JSON+="]"

# Update manifest with final data
cat > "$MANIFEST_FILE" << EOF
{
  "version": "1.0",
  "timestamp": "${TIMESTAMP}",
  "created_at": "$(date -Iseconds 2>/dev/null || date)",
  "hostname": "$(hostname)",
  "include_qdrant": ${INCLUDE_QDRANT},
  "git_commit": "${GIT_COMMIT}",
  "git_branch": "${GIT_BRANCH}",
  "backup_size": "${BACKUP_SIZE}",
  "file_count": ${FILE_COUNT},
  "files": ${FILES_JSON},
  "checksum": "pending"
}
EOF

success "Manifest finalized"

# ══════════════════════════════════════════════════════════════════════
# STEP 9: Compress Backup
# ══════════════════════════════════════════════════════════════════════
step "Compressing Backup"

ARCHIVE_NAME="${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${BACKUP_ROOT}/${ARCHIVE_NAME}"

info "Creating compressed archive..."

# Use tar with gzip
if tar -czf "$ARCHIVE_PATH" -C "$BACKUP_ROOT" "$TIMESTAMP" 2>/dev/null; then
    ARCHIVE_SIZE=$(du -h "$ARCHIVE_PATH" 2>/dev/null | cut -f1 || echo "unknown")
    success "Created archive: ${ARCHIVE_NAME} (${ARCHIVE_SIZE})"

    # Calculate checksum
    if command -v sha256sum &> /dev/null; then
        CHECKSUM=$(sha256sum "$ARCHIVE_PATH" | cut -d' ' -f1)
    elif command -v shasum &> /dev/null; then
        CHECKSUM=$(shasum -a 256 "$ARCHIVE_PATH" | cut -d' ' -f1)
    else
        CHECKSUM="unavailable"
    fi

    # Update manifest with checksum
    if command -v sed &> /dev/null; then
        sed -i.bak "s/\"checksum\": \"pending\"/\"checksum\": \"${CHECKSUM}\"/" "$MANIFEST_FILE" 2>/dev/null || true
        rm -f "${MANIFEST_FILE}.bak" 2>/dev/null || true
    fi

    # Remove uncompressed backup directory
    rm -rf "$BACKUP_DIR"
    success "Cleaned up temporary files"
else
    error "Failed to create compressed archive"
    exit 3
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 10: Cleanup Old Backups
# ══════════════════════════════════════════════════════════════════════
step "Cleaning Up Old Backups"

# Count existing backups
BACKUP_COUNT=$(ls -1 "${BACKUP_ROOT}"/*.tar.gz 2>/dev/null | wc -l | tr -d ' ')

if [ "$BACKUP_COUNT" -gt "$KEEP_BACKUPS" ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - KEEP_BACKUPS))
    info "Found ${BACKUP_COUNT} backups, keeping last ${KEEP_BACKUPS}"

    # Remove oldest backups (sorted by name which includes timestamp)
    ls -1 "${BACKUP_ROOT}"/*.tar.gz 2>/dev/null | head -n "$REMOVE_COUNT" | while read -r old_backup; do
        rm -f "$old_backup"
        info "Removed old backup: $(basename "$old_backup")"
    done

    success "Removed ${REMOVE_COUNT} old backup(s)"
else
    info "Backup count (${BACKUP_COUNT}) within limit (${KEEP_BACKUPS})"
fi

# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${GREEN}${BOLD}==========================================="
echo "  Backup Complete!"
echo -e "===========================================${NC}"
echo ""
echo -e "${BOLD}Backup Details:${NC}"
echo -e "  Archive:     ${CYAN}${ARCHIVE_PATH}${NC}"
echo -e "  Size:        ${ARCHIVE_SIZE}"
echo -e "  Duration:    ${DURATION} seconds"
echo -e "  Files:       ${FILE_COUNT} items"
if [ "$CHECKSUM" != "unavailable" ]; then
    echo -e "  Checksum:    ${CHECKSUM:0:16}..."
fi
echo ""
echo -e "${BOLD}Contents:${NC}"
echo "  - ${DB_COUNT} database(s)"
echo "  - ${CONFIG_COUNT} configuration file(s)"
echo "  - ${STATE_COUNT} state file(s)"
echo "  - BM25 index"
if [ "$INCLUDE_QDRANT" = true ]; then
    echo "  - Qdrant vector data"
fi
echo ""
echo -e "${BOLD}Restore command:${NC}"
echo "  bash scripts/restore.sh ${ARCHIVE_PATH}"
echo ""

exit 0
