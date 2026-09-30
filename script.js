function togglePassword(inputId, button) {
    const input = document.getElementById(inputId);

    if (!input) {
        return;
    }

    if (input.type === "password") {
        input.type = "text";
        button.textContent = "🙈";
    } else {
        input.type = "password";
        button.textContent = "👁️";
    }
}

console.log("Waste Management System loaded successfully.");
