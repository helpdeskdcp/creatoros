import Link from "next/link";

export const metadata = {
  title: "Terms of Service — CreatorOS",
};

export default function TermsPage() {
  return (
    <div className="mx-auto min-h-screen max-w-2xl px-4 py-12">
      <Link href="/login" className="text-sm text-brand-500 hover:underline">
        ← Back to CreatorOS
      </Link>
      <h1 className="mt-4 text-2xl font-bold">Terms of Service</h1>
      <p className="mt-1 text-sm muted">Last updated: 2026-09-12</p>

      <div className="mt-6 space-y-6 text-sm leading-relaxed">
        <section>
          <h2 className="mb-2 text-base font-semibold">Using CreatorOS</h2>
          <p>
            CreatorOS is provided to help you plan, generate, and analyze content for your own
            YouTube channel. By using CreatorOS, you agree to use it only for your own channel, or
            a channel you are explicitly authorized to manage.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Your responsibilities</h2>
          <ul className="ml-5 list-disc space-y-1">
            <li>You are responsible for the accuracy of any content you choose to publish.</li>
            <li>
              AI-generated suggestions (hooks, titles, scripts, SEO, thumbnail briefs) are drafts —
              you are responsible for reviewing them before publishing.
            </li>
            <li>You must not use CreatorOS to violate YouTube&apos;s Terms of Service or Community Guidelines.</li>
            <li>Keep your account credentials confidential.</li>
          </ul>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Publishing safety</h2>
          <p>
            Every automated publish action passes a safety gate before anything is uploaded to
            your channel, and can be halted at any time via the in-app Control Center kill switch.
            You remain in control of what is actually published.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">No warranty</h2>
          <p>
            CreatorOS is provided &quot;as is,&quot; without warranty of any kind. Metrics and AI
            output are best-effort and may be estimated or incomplete where real data is
            unavailable — CreatorOS labels these cases explicitly rather than guessing silently.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Changes</h2>
          <p>
            These terms may be updated as CreatorOS evolves. Continued use after a change means
            you accept the updated terms.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Contact</h2>
          <p>
            Questions about these terms:{" "}
            <a href="mailto:dcpstudio1982@gmail.com" className="text-brand-500 hover:underline">
              dcpstudio1982@gmail.com
            </a>
          </p>
        </section>
      </div>
    </div>
  );
}
