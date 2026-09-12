import { ReactNode } from "react";

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-6 mt-2">
      <h1 className="text-2xl font-bold">{title}</h1>
      {description && <p className="mt-1 muted">{description}</p>}
    </div>
  );
}

export function LoadingState() {
  return <div className="muted py-10 text-center text-sm">Loading…</div>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      {message}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div
      className="rounded-lg border border-dashed p-8 text-center text-sm muted"
      style={{ borderColor: "rgb(var(--border))" }}
    >
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
}) {
  const base = "rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-50";
  const styles = {
    primary: "bg-brand-500 text-white hover:bg-brand-600",
    secondary: "border hover:bg-black/5 dark:hover:bg-white/10",
    danger: "bg-red-600 text-white hover:bg-red-700",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${styles} ${className}`}
      style={variant === "secondary" ? { borderColor: "rgb(var(--border))" } : undefined}
    >
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-500 ${props.className ?? ""}`}
      style={{ borderColor: "rgb(var(--border))" }}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-500 ${props.className ?? ""}`}
      style={{ borderColor: "rgb(var(--border))" }}
    />
  );
}

export function Badge({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "success" | "warning" | "danger" }) {
  const styles = {
    default: "bg-black/5 dark:bg-white/10",
    success: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
    warning: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
    danger: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  }[tone];
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}>{children}</span>;
}
