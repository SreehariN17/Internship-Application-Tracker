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

function safeResourceUrl(value) {
  if (typeof value !== "string" || !value.trim() || value.length > 2048) return null;
  const trimmed = value.trim();
  if (/[\s\u0000-\u001f\u007f\\<>"{}|^`]/u.test(trimmed) || /%(?![0-9a-f]{2})/i.test(trimmed)) return null;
  try {
    // No base URL: relative links must not be silently accepted.
    const parsed = new URL(trimmed);
    if (!/^https?:\/\//i.test(trimmed) || !["http:", "https:"].includes(parsed.protocol) ||
        !parsed.hostname || parsed.username || parsed.password || trimmed.split("/")[2].includes("@")) return null;
    return parsed.href;
  } catch (error) {
    return null;
  }
}

function createResourceLink(label, value) {
  const destination = safeResourceUrl(value);
  if (!destination) return null;
  const link = document.createElement("a");
  link.href = destination;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  link.setAttribute("aria-label", label + " (opens in a new tab)");
  return link;
}

function createResourcesCell(application) {
  const cell = document.createElement("td");
  cell.className = "resources-cell";
  const links = document.createElement("div");
  links.className = "resource-links";
  for (const [label, url] of [["Job Posting", application.job_posting_url],
                             ["Check Status", application.application_portal_url]]) {
    const link = createResourceLink(label, url);
    if (link) links.append(link);
  }
  const emailList = document.createElement("ul");
  for (const email of application.email_links ?? []) {
    const link = createResourceLink(email.label, email.url);
    if (link) {
      const item = document.createElement("li");
      item.append(link);
      emailList.append(item);
    }
  }
  if (emailList.children.length) {
    const details = document.createElement("details");
    details.className = "email-panel";
    const summary = document.createElement("summary");
    summary.textContent = "Important Emails (" + emailList.children.length + ")";
    details.append(summary, emailList);
    links.append(details);
  }
  if (links.children.length) cell.append(links);
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
    createResourcesCell(application),
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
const emailRows = document.getElementById("email-link-rows");
const addEmailButton = document.getElementById("add-email-link");
const resourceFields = document.getElementById("resource-fields");
let emailSequence = 0;

function resetResourceFields() {
  emailRows.replaceChildren();
  addEmailButton.disabled = false;
  resourceFields.open = false;
}

function addEmailRow() {
  if (emailRows.children.length >= 20 || submitting) return;
  emailSequence += 1;
  const row = document.createElement("div");
  row.className = "email-link-row";
  for (const [name, title, placeholder, maxLength] of [
    ["label", "Email label", "e.g. Assessment invitation", 120],
    ["url", "Email web link", "https://mail.google.com/mail/u/0/#inbox/…", 2048],
  ]) {
    const field = document.createElement("div");
    field.className = "form-field";
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.id = "email-" + name + "-" + emailSequence;
    input.className = "email-" + name;
    input.type = name === "url" ? "url" : "text";
    input.maxLength = maxLength;
    input.placeholder = placeholder;
    label.htmlFor = input.id;
    label.textContent = title;
    field.append(label, input);
    row.append(field);
  }
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "button button-secondary remove-email";
  remove.textContent = "Remove email link";
  remove.addEventListener("click", () => {
    row.remove();
    addEmailButton.disabled = false;
    addEmailButton.focus();
  });
  row.append(remove);
  emailRows.append(row);
  addEmailButton.disabled = emailRows.children.length >= 20;
  row.querySelector("input").focus();
}

function collectResourceFields() {
  const resources = { email_links: [] };
  for (const [field, id] of [["job_posting_url", "job-posting-url"],
                            ["application_portal_url", "application-portal-url"]]) {
    const value = document.getElementById(id).value.trim();
    if (value && !safeResourceUrl(value)) throw new Error("Please enter a valid HTTP or HTTPS URL without credentials.");
    resources[field] = value || null;
  }
  for (const row of emailRows.querySelectorAll(".email-link-row")) {
    const label = row.querySelector(".email-label").value.trim();
    const url = row.querySelector(".email-url").value.trim();
    if (!label && !url) continue;
    if (!label || label.length > 120 || !safeResourceUrl(url)) {
      throw new Error("Each email link needs a label (up to 120 characters) and a valid HTTP or HTTPS URL without credentials.");
    }
    resources.email_links.push({ label, url });
  }
  return resources;
}

function todayLocalDate() {
  const today = new Date();
  // Avoid toISOString(): it uses UTC and can select the wrong local day.
  return [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0")].join("-");
}

function openApplicationDialog() {
  form.reset();
  resetResourceFields();
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
  try {
    Object.assign(data, collectResourceFields());
  } catch (error) {
    resourceFields.open = true;
    showFormError(error.message);
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
  resetResourceFields();
  notification.textContent = "Application added successfully.";
  notification.hidden = false;
  await loadApplications();
}

addEmailButton.addEventListener("click", addEmailRow);
// Reveal invalid optional inputs even when their details section is collapsed.
resourceFields.addEventListener("invalid", () => { resourceFields.open = true; }, true);
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
