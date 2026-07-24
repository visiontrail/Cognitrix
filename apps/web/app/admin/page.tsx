import AdminConsole from "@/components/admin/admin-console";

export const metadata = {
  title: "Cognitrix Control Plane",
  robots: { index: false, follow: false },
};

export default function AdminPage() {
  return <AdminConsole />;
}
