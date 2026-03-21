#!/bin/bash
# SME Research Assistant - Restore Script
# Restores databases, configs, and state from a backup archive.
#
# Usage:
#   bash scripts/restore.sh                    # List available backups
#   bash scripts/restore.sh <backup_path>      # Restore from specific backup
#   bash scripts/restore.sh --latest           # Restore from most recent backup
#   bash scripts/restore.sh --dry-run <path>   # Show what would be restored
#
# Exit codes:
#   0 - Success
#   1 - General error
#   2 - Backup file not found
#   3 - Invalid backup (missing manifest)
#   4 - Restore failed
#   5 - User cancelled

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
MAGENTA='\033[0;35m'
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
DRY_RUN=false
BACKUP_PATH=""
RESTORE_QDRANT=true
SKIP_SERVICES=false
FORCE=false

# ── Parse Arguments ──
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --latest)
            # Find most recent backup
            LATEST=$(ls -1t "${BACKUP_ROOT}"/*.tar.gz 2>/dev/null | head -1)
            if [ -n "$LATEST" ]; then
                BACKUP_PATH="$LATEST"
            else
                error "No backups found in ${BACKUP_ROOT}"
                exit 2
            fi
            shift
            ;;
        --no-qdrant)
            RESTORE_QDRANT=false
            shift
            ;;
        --skip-services)
            SKIP_SERVICES=true
            shift
            ;;
        --force|-f)
            FORCE=true
            shift
            ;;
        -h|--help)
            echo "SME Research Assistant - Restore Script"
            echo ""
            echo "Usage: bash scripts/restore.sh [OPTIONS] [BACKUP_PATH]"
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be restored without making changes"
            echo "  --latest           Restore from the most recent backup"
            echo "  --no-qdrant        Skip Qdrant restoration even if present in backup"
            echo "  --skip-services    Don't stop/start services during restore"
            echo "  --force, -f        Skip confirmation prompts"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Examples:"
            echo "  bash scripts/restore.sh                          # List available backups"
            echo "  bash scripts/restore.sh backups/20240101.tar.gz  # Restore specific backup"
            echo "  bash scripts/restore.sh --latest                 # Restore most recent"
            echo "  bash scripts/restore.sh --dry-run --latest       # Preview restore"
            exit 0
            ;;
        -*)
            error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
        *)
            BACKUP_PATH="$1"
            shift
            ;;
    esac
done

# ══════════════════════════════════════════════════════════════════════
# Header
# ══════════════════════════════════════════════════════════════════════
echo -e "${BOLD}==========================================="
echo "  SME Research Assistant - Restore"
echo -e "===========================================${NC}"
echo ""

# ══════════════════════════════════════════════════════════════════════
# List Backups (if no path provided)
# ══════════════════════════════════════════════════════════════════════
if [ -z "$BACKUP_PATH" ]; then
    step "Available Backups"

    if [ ! -d "$BACKUP_ROOT" ]; then
        warn "Backup directory not found: ${BACKUP_ROOT}"
        echo "  No backups have been created yet."
        echo "  Run: bash scripts/backup.sh"
        exit 0
    fi

    BACKUPS=($(ls -1t "${BACKUP_ROOT}"/*.tar.gz 2>/dev/null || true))

    if [ ${#BACKUPS[@]} -eq 0 ]; then
        warn "No backups found in ${BACKUP_ROOT}"
        echo "  Run: bash scripts/backup.sh"
        exit 0
    fi

    echo ""
    echo -e "${BOLD}Available backups:${NC}"
    echo ""
    printf "  ${BOLD}%-3s  %-25s  %-10s  %-20s${NC}\n" "#" "TIMESTAMP" "SIZE" "PATH"
    echo "  -------------------------------------------------------------------------"

    for i in "${!BACKUPS[@]}"; do
        backup_file="${BACKUPS[$i]}"
        backup_name=$(basename "$backup_file" .tar.gz)
        backup_size=$(du -h "$backup_file" 2>/dev/null | cut -f1 || echo "?")

        # Format timestamp if it matches our format
        if [[ "$backup_name" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
            formatted_date="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
        else
            formatted_date="$backup_name"
        fi

        if [ $i -eq 0 ]; then
            printf "  ${GREEN}%-3s  %-25s  %-10s  %-20s${NC} (latest)\n" "$((i+1))" "$formatted_date" "$backup_size" "$(basename "$backup_file")"
        else
            printf "  %-3s  %-25s  %-10s  %-20s\n" "$((i+1))" "$formatted_date" "$backup_size" "$(basename "$backup_file")"
        fi
    done

    echo ""
    echo -e "${BOLD}To restore a backup:${NC}"
    echo "  bash scripts/restore.sh ${BACKUPS[0]}"
    echo "  bash scripts/restore.sh --latest"
    echo ""
    echo -e "${BOLD}To preview what will be restored:${NC}"
    echo "  bash scripts/restore.sh --dry-run --latest"
    echo ""
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════
# Validate Backup
# ══════════════════════════════════════════════════════════════════════
step "Validating Backup"

# Check if backup file exists
if [ ! -f "$BACKUP_PATH" ]; then
    # Try relative to backup root
    if [ -f "${BACKUP_ROOT}/${BACKUP_PATH}" ]; then
        BACKUP_PATH="${BACKUP_ROOT}/${BACKUP_PATH}"
    else
        error "Backup file not found: ${BACKUP_PATH}"
        exit 2
    fi
fi

success "Backup file found: $(basename "$BACKUP_PATH")"

# Get backup size
BACKUP_SIZE=$(du -h "$BACKUP_PATH" 2>/dev/null | cut -f1 || echo "unknown")
info "Backup size: ${BACKUP_SIZE}"

# Create temp directory for extraction
TEMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t 'sme_restore')
trap "rm -rf '$TEMP_DIR'" EXIT

info "Extracting backup for verification..."

# Extract backup
if ! tar -xzf "$BACKUP_PATH" -C "$TEMP_DIR" 2>/dev/null; then
    error "Failed to extract backup archive"
    exit 3
fi

# Find the backup directory inside temp
EXTRACTED_DIR=$(ls -1 "$TEMP_DIR" | head -1)
BACKUP_CONTENT="${TEMP_DIR}/${EXTRACTED_DIR}"

if [ ! -d "$BACKUP_CONTENT" ]; then
    error "Invalid backup structure"
    exit 3
fi

# Check for manifest
MANIFEST_FILE="${BACKUP_CONTENT}/manifest.json"
if [ ! -f "$MANIFEST_FILE" ]; then
    error "Invalid backup: manifest.json not found"
    echo "  This backup may be corrupted or from an incompatible version"
    exit 3
fi
success "Manifest found"

# ══════════════════════════════════════════════════════════════════════
# Parse Manifest
# ══════════════════════════════════════════════════════════════════════
step "Reading Backup Manifest"

# Parse manifest (basic parsing without jq)
if command -v jq &> /dev/null; then
    MANIFEST_TIMESTAMP=$(jq -r '.timestamp' "$MANIFEST_FILE" 2>/dev/null || echo "unknown")
    MANIFEST_CREATED=$(jq -r '.created_at' "$MANIFEST_FILE" 2>/dev/null || echo "unknown")
    MANIFEST_HOSTNAME=$(jq -r '.hostname' "$MANIFEST_FILE" 2>/dev/null || echo "unknown")
    MANIFEST_QDRANT=$(jq -r '.include_qdrant' "$MANIFEST_FILE" 2>/dev/null || echo "false")
    MANIFEST_GIT=$(jq -r '.git_commit' "$MANIFEST_FILE" 2>/dev/null || echo "unknown")
    MANIFEST_FILES=$(jq -r '.file_count' "$MANIFEST_FILE" 2>/dev/null || echo "unknown")
    MANIFEST_CHECKSUM=$(jq -r '.checksum' "$MANIFEST_FILE" 2>/dev/null || echo "unknown")
else
    # Fallback to grep/sed parsing
    MANIFEST_TIMESTAMP=$(grep -o '"timestamp": *"[^"]*"' "$MANIFEST_FILE" | sed 's/.*: *"\([^"]*\)"/\1/' || echo "unknown")
    MANIFEST_CREATED=$(grep -o '"created_at": *"[^"]*"' "$MANIFEST_FILE" | sed 's/.*: *"\([^"]*\)"/\1/' || echo "unknown")
    MANIFEST_HOSTNAME=$(grep -o '"hostname": *"[^"]*"' "$MANIFEST_FILE" | sed 's/.*: *"\([^"]*\)"/\1/' || echo "unknown")
    MANIFEST_QDRANT=$(grep -o '"include_qdrant": *[^,}]*' "$MANIFEST_FILE" | sed 's/.*: *//' || echo "false")
    MANIFEST_GIT=$(grep -o '"git_commit": *"[^"]*"' "$MANIFEST_FILE" | sed 's/.*: *"\([^"]*\)"/\1/' || echo "unknown")
    MANIFEST_FILES=$(grep -o '"file_count": *[0-9]*' "$MANIFEST_FILE" | sed 's/.*: *//' || echo "unknown")
    MANIFEST_CHECKSUM=$(grep -o '"checksum": *"[^"]*"' "$MANIFEST_FILE" | sed 's/.*: *"\([^"]*\)"/\1/' || echo "unknown")
fi

echo ""
echo -e "${BOLD}Backup Information:${NC}"
echo -e "  Timestamp:    ${CYAN}${MANIFEST_TIMESTAMP}${NC}"
echo -e "  Created:      ${MANIFEST_CREATED}"
echo -e "  Hostname:     ${MANIFEST_HOSTNAME}"
echo -e "  Git Commit:   ${MANIFEST_GIT:0:12}"
echo -e "  File Count:   ${MANIFEST_FILES}"
echo -e "  Includes Qdrant: ${MANIFEST_QDRANT}"
if [ "$MANIFEST_CHECKSUM" != "unknown" ] && [ "$MANIFEST_CHECKSUM" != "pending" ]; then
    echo -e "  Checksum:     ${MANIFEST_CHECKSUM:0:16}..."
fi

# ══════════════════════════════════════════════════════════════════════
# Verify Checksum (if available)
# ══════════════════════════════════════════════════════════════════════
if [ "$MANIFEST_CHECKSUM" != "unknown" ] && [ "$MANIFEST_CHECKSUM" != "pending" ] && [ "$MANIFEST_CHECKSUM" != "unavailable" ]; then
    step "Verifying Backup Integrity"

    if command -v sha256sum &> /dev/null; then
        ACTUAL_CHECKSUM=$(sha256sum "$BACKUP_PATH" | cut -d' ' -f1)
    elif command -v shasum &> /dev/null; then
        ACTUAL_CHECKSUM=$(shasum -a 256 "$BACKUP_PATH" | cut -d' ' -f1)
    else
        ACTUAL_CHECKSUM="unavailable"
        warn "Checksum verification not available (sha256sum/shasum not found)"
    fi

    if [ "$ACTUAL_CHECKSUM" != "unavailable" ]; then
        if [ "$ACTUAL_CHECKSUM" = "$MANIFEST_CHECKSUM" ]; then
            success "Checksum verified"
        else
            error "Checksum mismatch - backup may be corrupted"
            echo "  Expected: ${MANIFEST_CHECKSUM}"
            echo "  Actual:   ${ACTUAL_CHECKSUM}"
            if [ "$FORCE" != true ]; then
                exit 3
            else
                warn "Continuing due to --force flag"
            fi
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# Show What Will Be Restored
# ══════════════════════════════════════════════════════════════════════
step "Restore Preview"

echo ""
echo -e "${BOLD}The following items will be restored:${NC}"
echo ""

# Databases
if [ -d "${BACKUP_CONTENT}/databases" ]; then
    echo -e "  ${MAGENTA}Databases:${NC}"
    for db in "${BACKUP_CONTENT}/databases"/*.db 2>/dev/null; do
        if [ -f "$db" ]; then
            db_name=$(basename "$db")
            db_size=$(du -h "$db" 2>/dev/null | cut -f1 || echo "?")
            target="data/${db_name}"
            if [ -f "$target" ]; then
                echo -e "    ${YELLOW}[OVERWRITE]${NC} ${db_name} (${db_size})"
            else
                echo -e "    ${GREEN}[NEW]${NC} ${db_name} (${db_size})"
            fi
        fi
    done
fi

# Config files
if [ -d "${BACKUP_CONTENT}/config" ]; then
    echo -e "  ${MAGENTA}Configuration:${NC}"
    for config in "${BACKUP_CONTENT}/config"/* 2>/dev/null; do
        if [ -f "$config" ]; then
            config_name=$(basename "$config")
            if [ "$config_name" = ".env" ]; then
                target=".env"
            else
                target="config/${config_name}"
            fi
            if [ -f "$target" ]; then
                echo -e "    ${YELLOW}[OVERWRITE]${NC} ${config_name}"
            else
                echo -e "    ${GREEN}[NEW]${NC} ${config_name}"
            fi
        fi
    done
fi

# State files
if [ -d "${BACKUP_CONTENT}/state" ]; then
    echo -e "  ${MAGENTA}Pipeline State:${NC}"
    for state in "${BACKUP_CONTENT}/state"/*.json 2>/dev/null; do
        if [ -f "$state" ]; then
            state_name=$(basename "$state")
            target="data/${state_name}"
            if [ -f "$target" ]; then
                echo -e "    ${YELLOW}[OVERWRITE]${NC} ${state_name}"
            else
                echo -e "    ${GREEN}[NEW]${NC} ${state_name}"
            fi
        fi
    done
fi

# BM25 index
if [ -d "${BACKUP_CONTENT}/bm25_index" ]; then
    echo -e "  ${MAGENTA}BM25 Index:${NC}"
    bm25_size=$(du -sh "${BACKUP_CONTENT}/bm25_index" 2>/dev/null | cut -f1 || echo "?")
    if [ -d "data/bm25_index_tantivy" ]; then
        echo -e "    ${YELLOW}[OVERWRITE]${NC} bm25_index_tantivy/ (${bm25_size})"
    else
        echo -e "    ${GREEN}[NEW]${NC} bm25_index_tantivy/ (${bm25_size})"
    fi
fi

# Qdrant
if [ -d "${BACKUP_CONTENT}/qdrant" ] && [ "$RESTORE_QDRANT" = true ]; then
    echo -e "  ${MAGENTA}Qdrant Vector DB:${NC}"
    qdrant_size=$(du -sh "${BACKUP_CONTENT}/qdrant" 2>/dev/null | cut -f1 || echo "?")
    echo -e "    ${YELLOW}[RESTORE]${NC} qdrant_storage/ (${qdrant_size})"
elif [ -d "${BACKUP_CONTENT}/qdrant" ]; then
    echo -e "  ${MAGENTA}Qdrant Vector DB:${NC}"
    echo -e "    ${BLUE}[SKIPPED]${NC} (use without --no-qdrant to restore)"
fi

echo ""

# ══════════════════════════════════════════════════════════════════════
# Dry Run Exit
# ══════════════════════════════════════════════════════════════════════
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}${BOLD}DRY RUN MODE${NC} - No changes have been made"
    echo ""
    echo "To perform the actual restore, run:"
    echo "  bash scripts/restore.sh ${BACKUP_PATH}"
    echo ""
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════
# Confirmation
# ══════════════════════════════════════════════════════════════════════
if [ "$FORCE" != true ]; then
    echo -e "${YELLOW}${BOLD}WARNING:${NC} This will overwrite existing data!"
    echo ""
    read -p "Are you sure you want to restore from this backup? (y/N): " CONFIRM

    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        info "Restore cancelled by user"
        exit 5
    fi
    echo ""
fi

START_TIME=$(date +%s)

# ══════════════════════════════════════════════════════════════════════
# Stop Services
# ══════════════════════════════════════════════════════════════════════
if [ "$SKIP_SERVICES" != true ]; then
    step "Stopping Services"

    # Check if Docker Compose is available
    if docker compose version &> /dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        COMPOSE_CMD=""
    fi

    if [ -n "$COMPOSE_CMD" ] && [ -f "docker-compose.yml" ] || [ -f "docker-compose.yaml" ]; then
        info "Stopping Docker services..."
        $COMPOSE_CMD down 2>/dev/null || warn "Could not stop services (may not be running)"
        success "Services stopped"
    else
        info "No Docker Compose configuration found - skipping service stop"
    fi
else
    warn "Skipping service stop (--skip-services)"
fi

# ══════════════════════════════════════════════════════════════════════
# Create Pre-Restore Backup
# ══════════════════════════════════════════════════════════════════════
step "Creating Pre-Restore Safety Backup"

PRE_RESTORE_DIR="${PROJECT_ROOT}/.pre_restore_backup"
rm -rf "$PRE_RESTORE_DIR" 2>/dev/null || true
mkdir -p "$PRE_RESTORE_DIR"

# Backup current databases
if ls data/*.db &> /dev/null 2>&1; then
    cp data/*.db "$PRE_RESTORE_DIR/" 2>/dev/null || true
fi

# Backup current .env
if [ -f ".env" ]; then
    cp ".env" "$PRE_RESTORE_DIR/.env" 2>/dev/null || true
fi

success "Safety backup created at .pre_restore_backup/"

# ══════════════════════════════════════════════════════════════════════
# Restore Databases
# ══════════════════════════════════════════════════════════════════════
step "Restoring Databases"

mkdir -p data
RESTORE_COUNT=0

if [ -d "${BACKUP_CONTENT}/databases" ]; then
    for db in "${BACKUP_CONTENT}/databases"/*.db 2>/dev/null; do
        if [ -f "$db" ]; then
            db_name=$(basename "$db")
            cp "$db" "data/${db_name}"
            success "Restored ${db_name}"
            RESTORE_COUNT=$((RESTORE_COUNT + 1))
        fi
    done
fi

info "Restored ${RESTORE_COUNT} database(s)"

# ══════════════════════════════════════════════════════════════════════
# Restore Configuration
# ══════════════════════════════════════════════════════════════════════
step "Restoring Configuration"

mkdir -p config
CONFIG_COUNT=0

if [ -d "${BACKUP_CONTENT}/config" ]; then
    for config in "${BACKUP_CONTENT}/config"/* 2>/dev/null; do
        if [ -f "$config" ]; then
            config_name=$(basename "$config")
            if [ "$config_name" = ".env" ]; then
                cp "$config" ".env"
                success "Restored .env"
            elif [ "$config_name" = ".env.example" ]; then
                cp "$config" ".env.example"
                success "Restored .env.example"
            else
                cp "$config" "config/${config_name}"
                success "Restored config/${config_name}"
            fi
            CONFIG_COUNT=$((CONFIG_COUNT + 1))
        fi
    done
fi

info "Restored ${CONFIG_COUNT} configuration file(s)"

# ══════════════════════════════════════════════════════════════════════
# Restore Pipeline State
# ══════════════════════════════════════════════════════════════════════
step "Restoring Pipeline State"

STATE_COUNT=0

if [ -d "${BACKUP_CONTENT}/state" ]; then
    for state in "${BACKUP_CONTENT}/state"/*.json 2>/dev/null; do
        if [ -f "$state" ]; then
            state_name=$(basename "$state")
            cp "$state" "data/${state_name}"
            success "Restored ${state_name}"
            STATE_COUNT=$((STATE_COUNT + 1))
        fi
    done
fi

info "Restored ${STATE_COUNT} state file(s)"

# ══════════════════════════════════════════════════════════════════════
# Restore BM25 Index
# ══════════════════════════════════════════════════════════════════════
step "Restoring BM25 Index"

if [ -d "${BACKUP_CONTENT}/bm25_index" ]; then
    # Remove existing index
    rm -rf "data/bm25_index_tantivy" 2>/dev/null || true
    mkdir -p "data/bm25_index_tantivy"

    # Copy index files
    cp -r "${BACKUP_CONTENT}/bm25_index"/* "data/bm25_index_tantivy/" 2>/dev/null || true
    success "Restored BM25 index"
else
    info "No BM25 index in backup (skipping)"
fi

# ══════════════════════════════════════════════════════════════════════
# Restore Papers Directory
# ══════════════════════════════════════════════════════════════════════
step "Restoring Papers Directory"

if [ -d "${BACKUP_CONTENT}/papers" ]; then
    # Count PDF files in backup
    PAPERS_COUNT=$(find "${BACKUP_CONTENT}/papers" -type f -name "*.pdf" 2>/dev/null | wc -l)

    if [ "$PAPERS_COUNT" -gt 0 ]; then
        # Create DataBase/Papers directory if it doesn't exist
        mkdir -p "DataBase/Papers"

        # Restore papers
        cp -r "${BACKUP_CONTENT}/papers"/* "DataBase/Papers/" 2>/dev/null || {
            # Try restoring to DataBase root if Papers subdirectory fails
            cp -r "${BACKUP_CONTENT}/papers"/* "DataBase/" 2>/dev/null || true
        }

        RESTORED_COUNT=$(find "DataBase" -type f -name "*.pdf" 2>/dev/null | wc -l)
        success "Restored ${RESTORED_COUNT} PDF files to DataBase/"
    else
        info "Papers backup exists but contains no PDF files"
    fi
else
    info "No papers directory in backup (skipping)"
fi

# ══════════════════════════════════════════════════════════════════════
# Restore Qdrant (if present and requested)
# ══════════════════════════════════════════════════════════════════════
if [ -d "${BACKUP_CONTENT}/qdrant" ] && [ "$RESTORE_QDRANT" = true ]; then
    step "Restoring Qdrant Vector Database"

    # Check if we should restore to local directory or Docker volume
    if [ -d "qdrant_storage" ]; then
        info "Restoring to local qdrant_storage directory..."
        rm -rf "qdrant_storage" 2>/dev/null || true
        mkdir -p "qdrant_storage"
        cp -r "${BACKUP_CONTENT}/qdrant"/* "qdrant_storage/" 2>/dev/null || true
        success "Restored Qdrant to local storage"
    elif docker volume inspect sme_qdrant_data &> /dev/null 2>&1; then
        info "Restoring to Docker volume..."
        docker run --rm \
            -v "${BACKUP_CONTENT}/qdrant":/source:ro \
            -v sme_qdrant_data:/target \
            alpine sh -c "rm -rf /target/* && cp -r /source/* /target/" 2>/dev/null || {
            warn "Could not restore Qdrant to Docker volume"
            mkdir -p "qdrant_storage"
            cp -r "${BACKUP_CONTENT}/qdrant"/* "qdrant_storage/" 2>/dev/null || true
            success "Restored Qdrant to local storage instead"
        }
        success "Restored Qdrant to Docker volume"
    else
        mkdir -p "qdrant_storage"
        cp -r "${BACKUP_CONTENT}/qdrant"/* "qdrant_storage/" 2>/dev/null || true
        success "Restored Qdrant to local storage"
    fi
elif [ -d "${BACKUP_CONTENT}/qdrant" ]; then
    info "Skipping Qdrant restore (--no-qdrant specified)"
else
    info "No Qdrant data in backup"
fi

# ══════════════════════════════════════════════════════════════════════
# Start Services
# ══════════════════════════════════════════════════════════════════════
if [ "$SKIP_SERVICES" != true ]; then
    step "Starting Services"

    if [ -n "$COMPOSE_CMD" ] && [ -f "docker-compose.yml" ] || [ -f "docker-compose.yaml" ]; then
        info "Starting Docker services..."
        if $COMPOSE_CMD up -d 2>/dev/null; then
            success "Services started"

            # Wait for services to be ready
            info "Waiting for services to initialize..."
            sleep 5
        else
            warn "Could not start services automatically"
            echo "  Run manually: docker compose up -d"
        fi
    fi
else
    warn "Skipping service start (--skip-services)"
fi

# ══════════════════════════════════════════════════════════════════════
# Verify Restoration
# ══════════════════════════════════════════════════════════════════════
step "Verifying Restoration"

VERIFY_ERRORS=0

# Check databases
for db in "data/auth.db" "data/sme.db" "data/papers.db"; do
    if [ -f "$db" ]; then
        # Try to open with sqlite3 if available
        if command -v sqlite3 &> /dev/null; then
            if sqlite3 "$db" "SELECT 1;" &> /dev/null; then
                success "$(basename $db) is valid"
            else
                error "$(basename $db) may be corrupted"
                VERIFY_ERRORS=$((VERIFY_ERRORS + 1))
            fi
        else
            success "$(basename $db) exists"
        fi
    fi
done

# Check .env
if [ -f ".env" ]; then
    success ".env file present"
else
    warn ".env file missing"
fi

# Check config files
if ls config/*.yaml &> /dev/null 2>&1; then
    success "Config files present"
else
    warn "Config files missing"
fi

if [ $VERIFY_ERRORS -gt 0 ]; then
    warn "Restoration completed with ${VERIFY_ERRORS} error(s)"
    echo "  Your pre-restore backup is at: .pre_restore_backup/"
else
    success "All verifications passed"

    # Clean up pre-restore backup
    info "Cleaning up safety backup..."
    rm -rf "$PRE_RESTORE_DIR" 2>/dev/null || true
fi

# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${GREEN}${BOLD}==========================================="
echo "  Restore Complete!"
echo -e "===========================================${NC}"
echo ""
echo -e "${BOLD}Restore Summary:${NC}"
echo -e "  Source:       ${CYAN}$(basename "$BACKUP_PATH")${NC}"
echo -e "  Duration:     ${DURATION} seconds"
echo -e "  Databases:    ${RESTORE_COUNT} restored"
echo -e "  Configs:      ${CONFIG_COUNT} restored"
echo -e "  State files:  ${STATE_COUNT} restored"
echo ""

if [ "$SKIP_SERVICES" != true ] && [ -n "$COMPOSE_CMD" ]; then
    echo -e "${BOLD}Service Status:${NC}"
    $COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || $COMPOSE_CMD ps 2>/dev/null || echo "  Run: docker compose ps"
    echo ""
fi

echo -e "${BOLD}Next Steps:${NC}"
echo "  1. Verify services are running: docker compose ps"
echo "  2. Check application logs: docker compose logs -f"
echo "  3. Test the application: http://localhost:3030"
echo ""

if [ $VERIFY_ERRORS -gt 0 ]; then
    echo -e "${YELLOW}${BOLD}Warning:${NC} Some verifications failed."
    echo "  If issues persist, restore from .pre_restore_backup/"
    echo ""
    exit 4
fi

exit 0
