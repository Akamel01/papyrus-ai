import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorBoundaryState {
    hasError: boolean;
    error: Error | null;
}

/**
 * Error boundary component for catching and recovering from React rendering errors.
 * Wraps page content; shows a friendly error UI instead of a white screen.
 */
export class ErrorBoundary extends React.Component<
    { children: React.ReactNode; fallback?: React.ReactNode },
    ErrorBoundaryState
> {
    constructor(props: { children: React.ReactNode; fallback?: React.ReactNode }) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error: Error): ErrorBoundaryState {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
        console.error('[ErrorBoundary] Caught error:', error, errorInfo);
    }

    handleRetry = () => {
        this.setState({ hasError: false, error: null });
    };

    render() {
        if (this.state.hasError) {
            if (this.props.fallback) return this.props.fallback;

            return (
                <div
                    role="alert"
                    aria-live="assertive"
                    className="flex flex-col items-center justify-center min-h-[400px] p-8"
                >
                    <div className="flex flex-col items-center gap-4 max-w-md text-center">
                        <div className="w-16 h-16 rounded-full bg-red-500/10 flex items-center justify-center">
                            <AlertTriangle className="w-8 h-8 text-red-400" aria-hidden="true" />
                        </div>
                        <h2 className="text-xl font-semibold text-white">Something went wrong</h2>
                        <p className="text-sm text-zinc-400">
                            {this.state.error?.message || 'An unexpected error occurred.'}
                        </p>
                        <button
                            onClick={this.handleRetry}
                            className="flex items-center gap-2 px-4 py-2 mt-2 text-sm font-medium text-white bg-zinc-700 rounded-lg hover:bg-zinc-600 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
                            aria-label="Try again"
                        >
                            <RefreshCw className="w-4 h-4" aria-hidden="true" />
                            Try Again
                        </button>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

/**
 * Loading spinner for data fetching states.
 * Uses ARIA live regions for screen reader announcements.
 */
export function LoadingState({ message = 'Loading...' }: { message?: string }) {
    return (
        <div
            role="status"
            aria-live="polite"
            className="flex flex-col items-center justify-center min-h-[200px] p-8"
        >
            <div className="w-8 h-8 border-2 border-zinc-600 border-t-blue-500 rounded-full animate-spin" aria-hidden="true" />
            <p className="mt-4 text-sm text-zinc-400">{message}</p>
        </div>
    );
}

/**
 * Empty state for zero-data views.
 */
export function EmptyState({
    icon: Icon,
    title,
    description,
}: {
    icon?: React.ElementType;
    title: string;
    description?: string;
}) {
    return (
        <div role="status" className="flex flex-col items-center justify-center min-h-[200px] p-8 text-center">
            {Icon && (
                <div className="w-12 h-12 rounded-full bg-zinc-800 flex items-center justify-center mb-3">
                    <Icon className="w-6 h-6 text-zinc-500" aria-hidden="true" />
                </div>
            )}
            <h3 className="text-sm font-medium text-zinc-300">{title}</h3>
            {description && <p className="mt-1 text-xs text-zinc-500">{description}</p>}
        </div>
    );
}
