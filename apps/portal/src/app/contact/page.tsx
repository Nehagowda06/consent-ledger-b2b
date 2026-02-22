"use client";

import { useState } from "react";
import { Mail, MessageSquareHeart, Phone } from "lucide-react";
import { TopNavbar } from "@/components/top-navbar";
import { SiteFooter } from "@/components/site-footer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";

const FAQ_ITEMS = [
  {
    question: "How quickly do you respond?",
    answer: "Most inquiries receive a reply within one business day.",
  },
  {
    question: "Can I request a tailored demo?",
    answer: "Yes. Include your use case and team size in your message.",
  },
  {
    question: "Do you support enterprise onboarding?",
    answer: "Yes. We provide structured onboarding for security and compliance teams.",
  },
];

export default function ContactPage() {
  const [submitted, setSubmitted] = useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <section className="hero-shell">
        <TopNavbar dark />
        <div className="mx-auto w-full max-w-5xl px-6 py-18 text-white">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Contact</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Talk to the Consent Ledger team.</h1>
          <p className="mt-3 max-w-3xl text-slate-300">
            Send your questions about implementation, compliance workflows, or integration planning.
          </p>
        </div>
      </section>

      <main className="mx-auto grid w-full max-w-5xl flex-1 gap-6 px-6 py-10 md:grid-cols-[1.2fr,0.8fr]">
        <Card className="border-slate-200">
          <CardHeader>
            <CardTitle>Contact Form</CardTitle>
            <CardDescription>UI only. This form does not submit to a backend yet.</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                setSubmitted(true);
              }}
            >
              <div className="grid gap-4 md:grid-cols-2">
                <Input placeholder="First name" required />
                <Input placeholder="Last name" required />
              </div>
              <Input type="email" placeholder="Work email" required />
              <Input placeholder="Company" />
              <select className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm">
                <option>General inquiry</option>
                <option>Request demo</option>
                <option>Partnership</option>
                <option>Support</option>
              </select>
              <Textarea placeholder="Tell us what you need..." className="min-h-32" required />
              <Button type="submit" className="bg-indigo-500 hover:bg-indigo-600">
                Send Message
              </Button>
              {submitted ? (
                <p className="text-sm text-emerald-700">Thanks, your message is captured in the UI state.</p>
              ) : null}
            </form>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>Direct Channels</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-slate-600">
              <p className="flex items-center gap-2">
                <Mail className="h-4 w-4 text-indigo-600" />
                support@consentledger.example
              </p>
              <p className="flex items-center gap-2">
                <Phone className="h-4 w-4 text-emerald-600" />
                +1 (555) 010-2048
              </p>
              <p className="flex items-center gap-2">
                <MessageSquareHeart className="h-4 w-4 text-indigo-600" />
                Enterprise onboarding available
              </p>
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>FAQ</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {FAQ_ITEMS.map((item, idx) => (
                <div key={item.question}>
                  <h3 className="text-sm font-semibold text-slate-900">{item.question}</h3>
                  <p className="mt-1 text-sm text-slate-600">{item.answer}</p>
                  {idx < FAQ_ITEMS.length - 1 ? <Separator className="mt-4" /> : null}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
