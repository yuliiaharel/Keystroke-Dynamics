import { addSample, login, register } from "../api";
import { KeystrokeCapture } from "../capture";
import { clearError, requireElement, showError } from "../ui";

const step1 = requireElement<HTMLElement>("step1");
const step2 = requireElement<HTMLElement>("step2");
const stepDone = requireElement<HTMLElement>("step-done");

const registerForm = requireElement<HTMLFormElement>("register-form");
const usernameInput = requireElement<HTMLInputElement>("username");
const passwordInput = requireElement<HTMLInputElement>("password");
const registerError = requireElement<HTMLElement>("register-error");

const sampleTextarea = requireElement<HTMLTextAreaElement>("sample-text");
const sampleCountEl = requireElement<HTMLElement>("sample-count");
const sampleForm = requireElement<HTMLFormElement>("sample-form");
const sampleError = requireElement<HTMLElement>("sample-error");

const capture = new KeystrokeCapture();
capture.attach(sampleTextarea);
sampleTextarea.addEventListener("keyup", () => {
  sampleCountEl.textContent = `${capture.count} key events recorded`;
});

registerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearError(registerError);

  void (async () => {
    try {
      await register(usernameInput.value, passwordInput.value);
      // Registering does not start a session by itself -- log in with
      // the same credentials (no sample yet) so the enrollment step
      // below has an authenticated session to add the sample to.
      await login(usernameInput.value, passwordInput.value);
      step1.hidden = true;
      step2.hidden = false;
      sampleTextarea.focus();
    } catch (error) {
      showError(registerError, error);
    }
  })();
});

sampleForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearError(sampleError);

  if (capture.count === 0) {
    showError(sampleError, "Type something before submitting.");
    return;
  }

  void (async () => {
    try {
      // One sample sent on explicit submit -- never resent, never
      // sent piecemeal as the log grows.
      await addSample(capture.sample());
      step2.hidden = true;
      stepDone.hidden = false;
    } catch (error) {
      showError(sampleError, error);
    }
  })();
});
