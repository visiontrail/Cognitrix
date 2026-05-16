import AdminSkillsPage from "@/components/admin/admin-skills-page";

// Page metadata stays deliberately generic: the route is hidden and we do not
// want non-superadmins (who get a "Not found" 404-style page) to learn its
// purpose via document.title or any other side-channel.
export const metadata = {
  title: "Not found",
};

export default function Page() {
  return <AdminSkillsPage />;
}
