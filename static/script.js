"use strict";

const panel = document.getElementById("applications-panel");
const tableBody = document.getElementById("applications-body");
const statusClasses = {
  Applied: "status-applied",
  Assessment: "status-assessment",
  Interview: "status-interview",
  Offer: "status-offer",
  Rejected: "status-rejected",
  Withdrawn: "status-withdrawn",
};

function showState(state, message = "") {
  document.getElementById("loading-state").hidden = state !== "loading";
  document.getElementById("empty-state").hidden = state !== "empty";
  document.getElementById("error-state").hidden = state !== "error";
  document.getElementById("table-container").hidden = state !== "ready";
  document.getElementById("error-state").textContent = message;
  panel.setAttribute("aria-busy", String(state === "loading"));
}

function createCell(value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value ?? "—";
  cell.className = className;
  return cell;
}

function createCompanyCell(name) {
  const cell = document.createElement("td");
  const content = document.createElement("div");
  content.className = "company-content";
  const initials = document.createElement("span");
  initials.className = "company-initials";
  initials.setAttribute("aria-hidden", "true");
  initials.textContent = (name ?? "").trim().split(/\s+/).slice(0, 2)
    .map(word => Array.from(word)[0] ?? "").join("").toUpperCase() || "?";
  const label = document.createElement("span");
  label.className = "company-cell";
  label.textContent = name ?? "—";
  content.append(initials, label);
  cell.append(content);
  return cell;
}

function createApplicationRow(application) {
  const row = document.createElement("tr");
  const statusCell = document.createElement("td");
  const badge = document.createElement("span");
  badge.classList.add("status-badge");
  if (Object.hasOwn(statusClasses, application.status)) {
    badge.classList.add(statusClasses[application.status]);
  }
  badge.textContent = application.status ?? "—";
  statusCell.append(badge);
  row.append(
    createCompanyCell(application.company_name),
    createCell(application.position),
    statusCell,
    // Keep the API's date string to avoid timezone-based date shifts.
    createCell(application.applied_date, "date-cell"),
    createCell(application.notes, "notes-cell"),
  );
  return row;
}

function renderApplications(applications) {
  tableBody.replaceChildren();
  // Append in API order; the backend already sorts applications.
  for (const application of applications) {
    tableBody.append(createApplicationRow(application));
  }
  showState(applications.length ? "ready" : "empty");
}

async function loadApplications() {
  showState("loading");
  try {
    const response = await fetch("/applications", { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error("Application request failed.");
    }
    const data = await response.json();
    if (!Array.isArray(data.applications)) {
      throw new Error("Unexpected application response.");
    }
    renderApplications(data.applications);
  } catch (error) {
    showState("error", "We couldn’t load your applications. Please refresh the page to try again.");
  }
}

const dialog = document.getElementById("application-dialog");
const form = document.getElementById("application-form");
const addButton = document.getElementById("add-application");
const submitButton = document.getElementById("submit-application");
const cancelButton = document.getElementById("cancel-dialog");
const closeButton = document.getElementById("close-dialog");
const formError = document.getElementById("form-error");
const notification = document.getElementById("success-notification");
let submitting = false;

function todayLocalDate() {
  const today = new Date();
  // Avoid toISOString(): it uses UTC and can select the wrong local day.
  return [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0")].join("-");
}

function openApplicationDialog() {
  form.reset();
  formError.hidden = true;
  formError.textContent = "";
  notification.hidden = true;
  document.getElementById("applied-date").value = todayLocalDate();
  // Native dialog provides a modal focus boundary and Escape handling.
  dialog.showModal();
  document.getElementById("company-name").focus();
}

function closeApplicationDialog() {
  if (!submitting) dialog.close();
}

function setSubmitting(value) {
  submitting = value;
  submitButton.disabled = value;
  cancelButton.disabled = value;
  closeButton.disabled = value;
  document.getElementById("form-fields").disabled = value;
  form.setAttribute("aria-busy", String(value));
  submitButton.textContent = value ? "Saving…" : "Save Application";
}

function showFormError(message) {
  formError.textContent = message;
  formError.hidden = false;
  formError.focus();
}

async function submitApplication(event) {
  event.preventDefault();
  if (submitting || !form.reportValidity()) return;
  const values = new FormData(form);
  const data = {
    company_name: values.get("company_name").trim(),
    position: values.get("position").trim(),
    status: values.get("status"),
    applied_date: values.get("applied_date"),
    notes: values.get("notes").trim() || null,
  };
  if (!data.company_name || !data.position) {
    showFormError("Company name and position cannot be blank.");
    return;
  }
  if (!Object.hasOwn(statusClasses, data.status)) {
    showFormError("Please choose a valid application status.");
    return;
  }
  // The native date input validates calendar dates; the API validates again.
  if (!/^\d{4}-\d{2}-\d{2}$/.test(data.applied_date)) {
    showFormError("Please enter a valid applied date in YYYY-MM-DD format.");
    return;
  }
  formError.hidden = true;
  setSubmitting(true);
  try {
    const response = await fetch("/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(typeof result.error === "string" ? result.error : "Couldn’t save the application. Please try again.");
    }
  } catch (error) {
    setSubmitting(false);
    showFormError(error instanceof TypeError
      ? "We couldn’t reach the server. Check your connection and try again."
      : error.message);
    return;
  }
  // A failed table refresh must not be presented as a failed save.
  setSubmitting(false);
  dialog.close();
  form.reset();
  notification.textContent = "Application added successfully.";
  notification.hidden = false;
  await loadApplications();
}

addButton.addEventListener("click", openApplicationDialog);
cancelButton.addEventListener("click", closeApplicationDialog);
closeButton.addEventListener("click", closeApplicationDialog);
dialog.addEventListener("cancel", event => {
  // Keep the in-progress request visible and prevent accidental resubmission.
  if (submitting) event.preventDefault();
});
dialog.addEventListener("close", () => addButton.focus());
form.addEventListener("submit", submitApplication);

loadApplications();
