#!/bin/bash
# Enhanced Pipeline Runner with Proper Order and Monitoring

set -e  # Exit on error

# Configuration
PYTHON="/mnt/data/venv/bin/python"
PROJECT_ROOT="/mnt/data/AI4Deliberation"
LOG_DIR="${PROJECT_ROOT}/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Ensure we're in the project directory
cd "$PROJECT_ROOT"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"
}

print_error() {
    echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"
}

# Create log directory
mkdir -p "$LOG_DIR"

# Function to check if process is running
check_process() {
    if pgrep -f "enhanced_pipeline_orchestrator.py" > /dev/null; then
        print_error "Pipeline is already running!"
        exit 1
    fi
}

# Function to cleanup on exit
cleanup() {
    print_status "Cleaning up..."
    if [ ! -z "$MONITOR_PID" ]; then
        kill $MONITOR_PID 2>/dev/null || true
    fi
    if [ ! -z "$PIPELINE_PID" ]; then
        kill $PIPELINE_PID 2>/dev/null || true
    fi
}

trap cleanup EXIT

# Main execution
main() {
    clear
    echo "=============================================="
    echo "   AI4DELIBERATION ENHANCED PIPELINE"
    echo "=============================================="
    echo "Timestamp: $TIMESTAMP"
    echo "Python: $PYTHON"
    echo "Project: $PROJECT_ROOT"
    echo "Logs: $LOG_DIR"
    echo "=============================================="
    echo
    
    # Check if already running
    check_process
    
    # Parse arguments
    SKIP_FULL_ANON=""
    MONITOR_ONLY=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-full-anonymization)
                SKIP_FULL_ANON="--skip-full-anonymization"
                print_warning "Skipping full database anonymization"
                shift
                ;;
            --monitor-only)
                MONITOR_ONLY=true
                shift
                ;;
            *)
                echo "Unknown option: $1"
                echo "Usage: $0 [--skip-full-anonymization] [--monitor-only]"
                exit 1
                ;;
        esac
    done
    
    if [ "$MONITOR_ONLY" = true ]; then
        print_status "Starting monitor only..."
        $PYTHON pipeline_monitor.py
        exit 0
    fi
    
    # Start the enhanced pipeline
    print_status "Starting enhanced pipeline orchestrator..."
    print_status "This will:"
    if [ -z "$SKIP_FULL_ANON" ]; then
        echo "  1. Perform one-time full database anonymization"
    else
        echo "  1. [SKIPPED] Full database anonymization"
    fi
    echo "  2. Discover new consultations from opengov.gr"
    echo "  3. Scrape each consultation with immediate anonymization"
    echo "  4. Generate comprehensive logs for diagnostics"
    echo
    
    # Ask for confirmation
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Pipeline cancelled by user"
        exit 0
    fi
    
    # Start pipeline in background
    print_status "Launching pipeline..."
    nohup $PYTHON -u enhanced_pipeline_orchestrator.py $SKIP_FULL_ANON \
        > "${LOG_DIR}/enhanced_orchestrator_output_${TIMESTAMP}.log" 2>&1 &
    
    PIPELINE_PID=$!
    print_status "Pipeline started with PID: $PIPELINE_PID"
    
    # Wait a moment for it to start
    sleep 3
    
    # Check if pipeline is still running
    if ! kill -0 $PIPELINE_PID 2>/dev/null; then
        print_error "Pipeline failed to start!"
        echo "Check the log file:"
        echo "  ${LOG_DIR}/enhanced_orchestrator_output_${TIMESTAMP}.log"
        echo
        echo "Last 20 lines of log:"
        tail -20 "${LOG_DIR}/enhanced_orchestrator_output_${TIMESTAMP}.log"
        exit 1
    fi
    
    # Start the monitor
    print_status "Starting pipeline monitor..."
    echo
    sleep 2
    
    # Run monitor in foreground
    $PYTHON pipeline_monitor.py --refresh 2
}

# Run main function
main "$@"