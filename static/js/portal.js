/**
 * WiFi Captive Portal - Interactive Client Controller
 * Pure Vanilla JavaScript (Zero external dependencies)
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const planCards = document.querySelectorAll(".plan-card");
  const phoneInput = document.getElementById("mpesaPhone");
  const payBtn = document.getElementById("payBtn");
  const deviceMac = document.getElementById("deviceMac") ? document.getElementById("deviceMac").innerText.trim() : "";
  const deviceIp = document.getElementById("deviceIp") ? document.getElementById("deviceIp").innerText.trim() : "";
  const gatewayUrl = document.getElementById("gatewayUrl") ? document.getElementById("gatewayUrl").value : "http://www.google.com";

  // Modal Elements
  const modal = document.getElementById("paymentModal");
  const closeModalBtn = document.getElementById("closeModalBtn");
  const modalPendingState = document.getElementById("modalPendingState");
  const modalSuccessState = document.getElementById("modalSuccessState");
  const modalFailedState = document.getElementById("modalFailedState");
  const modalAmount = document.getElementById("modalAmount");
  const modalPhone = document.getElementById("modalPhone");
  const pollingStatusText = document.getElementById("pollingStatusText");
  const timeoutProgressBar = document.getElementById("timeoutProgressBar");
  const modalPlanActivated = document.getElementById("modalPlanActivated");
  const modalBrowseBtn = document.getElementById("modalBrowseBtn");
  const modalFailedMsg = document.getElementById("modalFailedMsg");
  const retryBtn = document.getElementById("retryBtn");

  // Active Session Timer
  const countdownEl = document.getElementById("liveCountdown");
  if (countdownEl) {
    initActiveTimer(countdownEl);
  }

  // State
  let selectedPlan = null;
  let pollInterval = null;
  let timerInterval = null;
  const POLL_TIMEOUT_SECONDS = 70;

  // 1. Plan Selection
  planCards.forEach((card) => {
    card.addEventListener("click", () => {
      planCards.forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");

      selectedPlan = {
        id: card.dataset.planId,
        price: parseInt(card.dataset.price, 10),
        name: card.dataset.name,
      };

      updatePayButton();
    });
  });

  // Select first popular plan by default if present
  const defaultCard = document.querySelector(".plan-card.popular") || planCards[0];
  if (defaultCard) {
    defaultCard.click();
  }

  // 2. Phone Input Validation
  if (phoneInput) {
    phoneInput.addEventListener("input", (e) => {
      // Allow only numbers and spaces
      let val = e.target.value.replace(/[^0-9]/g, "");
      if (val.length > 10 && val.startsWith("254")) {
        // e.g. 254712345678
      } else if (val.length > 10) {
        val = val.substring(0, 10);
      }
      e.target.value = formatPhoneNumber(val);
      updatePayButton();
    });

    phoneInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter" && !payBtn.disabled) {
        payBtn.click();
      }
    });
  }

  function formatPhoneNumber(num) {
    if (!num) return "";
    // Clean string
    const clean = num.replace(/\s+/g, "");
    if (clean.length > 7) {
      return `${clean.substring(0, 4)} ${clean.substring(4, 7)} ${clean.substring(7)}`;
    } else if (clean.length > 4) {
      return `${clean.substring(0, 4)} ${clean.substring(4)}`;
    }
    return clean;
  }

  function isPhoneValid(phone) {
    if (!phone) return false;
    const clean = phone.replace(/[^0-9]/g, "");
    // Valid Kenyan prefixes: 07XXXXXXXX, 01XXXXXXXX, 2547XXXXXXXX, 2541XXXXXXXX
    if (clean.length === 10 && (clean.startsWith("07") || clean.startsWith("01"))) {
      return true;
    }
    if (clean.length === 12 && (clean.startsWith("2547") || clean.startsWith("2541"))) {
      return true;
    }
    return false;
  }

  function updatePayButton() {
    if (!payBtn) return;
    const phone = phoneInput ? phoneInput.value : "";
    const valid = selectedPlan && isPhoneValid(phone);

    if (valid) {
      payBtn.disabled = false;
      payBtn.querySelector(".btn-text").innerText = `Pay KES ${selectedPlan.price} with M-Pesa`;
    } else if (selectedPlan) {
      payBtn.disabled = true;
      payBtn.querySelector(".btn-text").innerText = `Enter M-Pesa Number (KES ${selectedPlan.price})`;
    } else {
      payBtn.disabled = true;
      payBtn.querySelector(".btn-text").innerText = "Select a Plan to Pay";
    }
  }

  // 3. Initiate STK Push Payment
  if (payBtn) {
    payBtn.addEventListener("click", async () => {
      if (payBtn.disabled || !selectedPlan) return;

      const phone = phoneInput.value.replace(/[^0-9]/g, "");
      payBtn.disabled = true;
      payBtn.querySelector(".btn-text").innerText = "Sending STK Push...";

      try {
        const resp = await fetch("/api/create-charge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: selectedPlan.id,
            phone: phone,
            mac: deviceMac,
            ip: deviceIp,
            gateway_url: gatewayUrl,
          }),
        });

        const data = await resp.json();

        if (data.success && data.charge_id) {
          openPendingModal(data);
          startPolling(data.charge_id, selectedPlan);
        } else {
          alert(data.error || "Failed to trigger M-Pesa STK Push. Please check phone number.");
          updatePayButton();
        }
      } catch (err) {
        console.error("Payment initiation error:", err);
        alert("Could not contact hotspot server. Please reconnect to WiFi.");
        updatePayButton();
      }
    });
  }

  // 4. Modal Flow
  function openPendingModal(chargeData) {
    modalPendingState.classList.remove("hidden");
    modalSuccessState.classList.add("hidden");
    modalFailedState.classList.add("hidden");

    modalAmount.innerText = `KES ${chargeData.amount_kes}`;
    modalPhone.innerText = chargeData.phone;
    pollingStatusText.innerText = "Awaiting PIN on your phone...";
    modal.classList.remove("hidden");

    // Progress bar animation
    let elapsed = 0;
    timeoutProgressBar.style.width = "100%";
    clearInterval(timerInterval);
    timerInterval = setInterval(() => {
      elapsed += 1;
      const pct = Math.max(0, 100 - (elapsed / POLL_TIMEOUT_SECONDS) * 100);
      timeoutProgressBar.style.width = `${pct}%`;

      if (elapsed >= POLL_TIMEOUT_SECONDS) {
        clearInterval(timerInterval);
        clearInterval(pollInterval);
        showFailedState("Payment timed out. You did not enter your PIN in time.");
      }
    }, 1000);
  }

  function startPolling(chargeId, plan) {
    clearInterval(pollInterval);

    // Poll every 3 seconds as required
    pollInterval = setInterval(async () => {
      try {
        const resp = await fetch(`/api/charge-status/${encodeURIComponent(chargeId)}`);
        if (!resp.ok) return;

        const res = await resp.json();
        console.log("Poll status:", res);

        if (res.status === "succeeded" && res.access_granted) {
          clearInterval(pollInterval);
          clearInterval(timerInterval);
          showSuccessState(res, plan);
        } else if (res.status === "failed" || res.status === "expired") {
          clearInterval(pollInterval);
          clearInterval(timerInterval);
          showFailedState(res.message || "Payment declined or expired.");
        } else {
          // Still pending
          pollingStatusText.innerText = res.message || "Waiting for PIN entry...";
        }
      } catch (err) {
        console.warn("Polling network blip:", err);
      }
    }, 3000);
  }

  function showSuccessState(result, plan) {
    modalPendingState.classList.add("hidden");
    modalFailedState.classList.add("hidden");
    modalSuccessState.classList.remove("hidden");

    modalPlanActivated.innerText = `${plan.name} — Connected!`;
    const dest = result.gateway_url || gatewayUrl || "http://www.google.com";
    modalBrowseBtn.href = dest;

    // Client-side redirect / ping if configured
    if (result.client_redirect_url) {
      console.log("Pinging gateway client redirect URL:", result.client_redirect_url);
      const pingFrame = document.createElement("iframe");
      pingFrame.style.display = "none";
      pingFrame.src = result.client_redirect_url;
      document.body.appendChild(pingFrame);
    }

    // Auto-reload to show active session after 3 seconds or redirect
    setTimeout(() => {
      window.location.reload();
    }, 3500);
  }

  function showFailedState(message) {
    modalPendingState.classList.add("hidden");
    modalSuccessState.classList.add("hidden");
    modalFailedState.classList.remove("hidden");
    modalFailedMsg.innerText = message;
    updatePayButton();
  }

  // 5. Close / Retry Handlers
  if (closeModalBtn) {
    closeModalBtn.addEventListener("click", () => {
      clearInterval(pollInterval);
      clearInterval(timerInterval);
      modal.classList.add("hidden");
      updatePayButton();
    });
  }

  if (retryBtn) {
    retryBtn.addEventListener("click", () => {
      modal.classList.add("hidden");
      updatePayButton();
    });
  }

  // 6. Active Session Countdown Timer
  function initActiveTimer(el) {
    let seconds = parseInt(el.dataset.seconds, 10) || 0;

    function renderTime() {
      if (seconds <= 0) {
        el.innerText = "00:00:00 (Expired)";
        setTimeout(() => window.location.reload(), 2000);
        return;
      }
      const hrs = Math.floor(seconds / 3600);
      const mins = Math.floor((seconds % 3600) / 60);
      const secs = seconds % 60;
      el.innerText = `${pad(hrs)}:${pad(mins)}:${pad(secs)}`;
      seconds -= 1;
    }

    function pad(n) {
      return n < 10 ? `0${n}` : n;
    }

    renderTime();
    setInterval(renderTime, 1000);
  }

  // 7. Tab Switching (M-Pesa vs Voucher)
  window.switchCheckoutTab = function(mode) {
    const mpesaBtn = document.getElementById("tabMpesaBtn");
    const voucherBtn = document.getElementById("tabVoucherBtn");
    const mpesaPanel = document.getElementById("mpesaPanel");
    const voucherPanel = document.getElementById("voucherPanel");

    if (mode === "voucher") {
      if (mpesaBtn) mpesaBtn.classList.remove("active");
      if (voucherBtn) voucherBtn.classList.add("active");
      if (mpesaPanel) mpesaPanel.style.display = "none";
      if (voucherPanel) {
        voucherPanel.style.display = "flex";
        const vInput = document.getElementById("voucherCodeInput");
        if (vInput) vInput.focus();
      }
    } else {
      if (voucherBtn) voucherBtn.classList.remove("active");
      if (mpesaBtn) mpesaBtn.classList.add("active");
      if (voucherPanel) voucherPanel.style.display = "none";
      if (mpesaPanel) mpesaPanel.style.display = "block";
    }
  };

  // 8. Voucher Code Input & Redemption
  const voucherInput = document.getElementById("voucherCodeInput");
  const redeemBtn = document.getElementById("redeemVoucherBtn");
  const voucherErrorAlert = document.getElementById("voucherErrorAlert");

  if (voucherInput) {
    voucherInput.addEventListener("input", (e) => {
      let val = e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, "");
      if (val.startsWith("LUMO") && val.length > 4 && val[4] !== "-") {
        val = "LUMO-" + val.substring(4);
      }
      e.target.value = val;
      if (voucherErrorAlert) {
        voucherErrorAlert.style.display = "none";
      }
    });

    voucherInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        if (redeemBtn) redeemBtn.click();
      }
    });
  }

  if (redeemBtn) {
    redeemBtn.addEventListener("click", async () => {
      const code = voucherInput ? voucherInput.value.trim().toUpperCase() : "";
      if (!code) {
        showVoucherError("Please enter a voucher code.");
        if (voucherInput) voucherInput.focus();
        return;
      }

      redeemBtn.disabled = true;
      const btnText = redeemBtn.querySelector(".btn-text");
      if (btnText) btnText.innerText = "Validating Voucher...";
      if (voucherErrorAlert) voucherErrorAlert.style.display = "none";

      try {
        const response = await fetch("/api/redeem-voucher", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code: code,
            mac: deviceMac,
            ip: deviceIp,
            gateway_url: gatewayUrl,
          }),
        });

        const data = await response.json();

        if (response.ok && data.success && data.access_granted) {
          if (btnText) btnText.innerText = "Connected!";
          showSuccessState(data);
        } else {
          showVoucherError(data.error || "Could not validate voucher.");
          redeemBtn.disabled = false;
          if (btnText) btnText.innerText = "Connect with Voucher";
        }
      } catch (err) {
        console.error("Voucher redemption error:", err);
        showVoucherError("Network error. Please make sure you are connected to the WiFi.");
        redeemBtn.disabled = false;
        if (btnText) btnText.innerText = "Connect with Voucher";
      }
    });
  }

  function showVoucherError(msg) {
    if (voucherErrorAlert) {
      voucherErrorAlert.innerText = msg;
      voucherErrorAlert.style.display = "block";
    } else {
      alert(msg);
    }
  }
});

