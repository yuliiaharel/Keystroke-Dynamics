import { deleteProfile, login } from "../api";
import { KeystrokeCapture } from "../capture";
import { clearError, renderTypingResult, requireElement, showError } from "../ui";

const form = requireElement<HTMLFormElement>("auth-form");
const usernameInput = requireElement<HTMLInputElement>("username");
const passwordInput = requireElement<HTMLInputElement>("password");
const sampleTextarea = requireElement<HTMLTextAreaElement>("sample-text");
const formError = requireElement<HTMLElement>("form-error");
const resultEl = requireElement<HTMLElement>("result");
const deleteSection = requireElement<HTMLElement>("delete-section");
const deleteButton = requireElement<HTMLButtonElement>("delete-button");
const deleteError = requireElement<HTMLElement>("delete-error");

const capture = new KeystrokeCapture();
capture.attach(sampleTextarea);

form.addEventListener("submit", (event) => {
  event.preventDefault();
  clearError(formError);

  void (async () => {
    // Reset once the attempt resolves (success or failure), not
    // before -- otherwise a retry after a wrong password would blend
    // this attempt's keystrokes into the next one, scored against
    // timestamps relative to the first attempt's first keydown.
    try {
      // One combined check: password and typing sample submitted
      // together, scored in the same login call.
      const { typing_result } = await login(
        usernameInput.value,
        passwordInput.value,
        capture.sample(),
      );
      if (typing_result !== null) {
        renderTypingResult(resultEl, typing_result);
      }
      deleteSection.hidden = false;
    } catch (error) {
      showError(formError, error);
    } finally {
      capture.reset();
    }
  })();
});

deleteButton.addEventListener("click", () => {
  clearError(deleteError);
  void (async () => {
    try {
      await deleteProfile();
      deleteSection.hidden = true;
      resultEl.hidden = true;
    } catch (error) {
      showError(deleteError, error);
    }
  })();
});
