import Link from "next/link";

export const metadata = {
  title: "Privacy Policy — CreatorOS",
};

export default function PrivacyPolicyPage() {
  return (
    <div className="mx-auto min-h-screen max-w-2xl px-4 py-12">
      <Link href="/login" className="text-sm text-brand-500 hover:underline">
        ← Back to CreatorOS
      </Link>
      <h1 className="mt-4 text-2xl font-bold">Privacy Policy</h1>
      <p className="mt-1 text-sm muted">Last updated: 2026-09-12</p>

      <div className="mt-6 space-y-6 text-sm leading-relaxed">
        <section>
          <h2 className="mb-2 text-base font-semibold">What CreatorOS is</h2>
          <p>
            CreatorOS is a YouTube creator-intelligence and content-operations tool. It helps a
            creator plan, generate, and analyze content for their own YouTube channel.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Data we access from Google/YouTube</h2>
          <p>
            When you connect your channel via &quot;Connect with Google,&quot; CreatorOS requests
            the following YouTube Data API v3 / YouTube Analytics API scopes:
          </p>
          <ul className="ml-5 mt-2 list-disc space-y-1">
            <li>
              <code>youtube.readonly</code> — to read your channel&apos;s public and owner-level
              metadata (title, description, video list, statistics).
            </li>
            <li>
              <code>youtube.upload</code> — to publish videos to your channel only when you
              explicitly trigger a publish action inside CreatorOS. CreatorOS never uploads
              without an explicit user action, and every automated publish passes a safety gate
              before anything is uploaded (see the in-app Audit Log).
            </li>
            <li>
              <code>yt-analytics.readonly</code> — to read your own channel&apos;s performance
              analytics (views, watch time, retention, traffic sources) so CreatorOS can show
              accurate, non-fabricated metrics.
            </li>
          </ul>
          <p className="mt-2">
            We only ever access the YouTube channel belonging to the Google account you sign in
            with. CreatorOS does not access, request, or store data for any other channel.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">How we store this data</h2>
          <p>
            Your OAuth access and refresh tokens are encrypted at rest (Fernet/AES symmetric
            encryption) in our database and are never logged in plaintext, displayed in the UI, or
            included in the in-app Audit Log. Channel metadata and analytics snapshots you&apos;ve
            synced are stored so CreatorOS can show historical trends without repeatedly
            re-fetching from YouTube.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">What we never do</h2>
          <ul className="ml-5 list-disc space-y-1">
            <li>We never sell or share your YouTube data with third parties.</li>
            <li>We never use your data to train AI models.</li>
            <li>
              We never publish, edit, or delete anything on your channel without an explicit
              action you take inside CreatorOS.
            </li>
            <li>
              We never fabricate or estimate a metric and present it as real — CreatorOS labels
              every number as real, estimated, or insufficient-data.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Revoking access</h2>
          <p>
            You can revoke CreatorOS&apos;s access to your Google account at any time from your{" "}
            <a
              href="https://myaccount.google.com/permissions"
              target="_blank"
              rel="noreferrer"
              className="text-brand-500 hover:underline"
            >
              Google Account permissions page
            </a>
            . To request deletion of the CreatorOS account data associated with your email, contact
            us at the address below.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Other data we collect</h2>
          <p>
            Your CreatorOS account email and password (stored hashed, never in plaintext) are used
            solely to authenticate you. Content you create in CreatorOS (topics, hooks, titles,
            scripts, SEO plans, thumbnail briefs) is stored so you can retrieve and edit it later,
            and is visible only to your account.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-base font-semibold">Contact</h2>
          <p>
            Questions about this policy or a data-deletion request:{" "}
            <a href="mailto:dcpstudio1982@gmail.com" className="text-brand-500 hover:underline">
              dcpstudio1982@gmail.com
            </a>
          </p>
        </section>
      </div>
    </div>
  );
}
