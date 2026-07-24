import { redirect } from "next/navigation";

// Preserve the old deep link while consolidating administration into one shell.
export const metadata = {
  title: "Cognitrix Control Plane",
};

export default function Page() {
  redirect("/admin#skills");
}
