// Snipe Systems — SPDX-License-Identifier: Apache-2.0 | Copyright 2026 Snipe Systems
/* ================================================================
         THE LIBRARY — the growing archive.
         To add a piece, append one object to LIBRARY below:
           id     unique slug
           type   "Article" | "Research Report" | "Story"
           date   display date
           title, dek (one-line standfirst), excerpt (list view)
           mins   reading time in minutes
           body   array of blocks: { h: "heading" } or { p: "paragraph" }
         Entries render newest-first by array order (newest on top).
         ================================================================ */
      var LIBRARY = [
        {
          id: "voice-trading-agents",
          type: "Article",
          date: "October 17, 2026",
          title: "You Can Already Trade With Your Voice. Here's Why Almost Nobody Does.",
          dek: "Voice execution has existed since 2018. The technology got better. The trust didn't — and the failure that actually happened wasn't the one everyone fears.",
          excerpt: "In October 2018 you could place a real trade by talking to a smart speaker. Eight years on, almost nobody does. A deep-research pass through the products, the incidents, and the numbers nobody publishes — and what they say about where trading agents are actually going.",
          mins: 6,
          body: [
            { p: "In October 2018, you could say \u201CAlexa, ask TD Ameritrade to place a trade,\u201D state a spoken PIN, and the order went through. Eight years later, almost nobody trades by voice. The technology got better. The trust didn't." },
            { h: "The first generation died of indifference" },
            { p: "The 2016\u20132019 smart-speaker wave was mostly quotes and balance checks. Only TD Ameritrade actually executed trades by voice \u2014 a spoken PIN completed the order, and the skill also gave quotes and information on 75,000+ securities. Interactive Brokers' Alexa skill never placed an order; it handled quotes and account data only. The IBot that could place orders was a different, text-based product wearing the same name. HDFC's Arya in India recommended stocks, then texted you a link to finish the investment elsewhere." },
            { p: "Voice shopping itself flopped first: in 2018, only 2% of Alexa owners had bought anything by voice, and 90% of those never tried again. Amazon disputed the numbers. Voice trading \u2014 a far higher-stakes transaction \u2014 never stood a chance on a smart speaker." },
            { h: "The second generation moved into the app" },
            { p: "Webull's Vega, launched November 2025, is the only major retail product that takes voice orders: you speak, it shows you the interpreted ticket on screen, you confirm. Robinhood's Cortex takes voice as input but answers in text \u2014 and it drafts orders you must review and submit yourself. Interactive Brokers' Ask IBKR, launched October 2025, is research-only and typed. Schwab's Charley, announced September 30, 2026, does voice-or-text \u201Cselect tasks\u201D \u2014 whether voice alone can place a trade is unconfirmed." },
            { h: "The real breakthrough of 2026 wasn't voice at all" },
            { p: "Brokers opened their doors to text AI agents via MCP. That's where execution actually went autonomous. Robinhood's external-agent route ships with trade approvals off by default inside a dedicated, separately funded account \u2014 the agent trades, and you assume all risk. Interactive Brokers and Webull keep a human submit step. Public's agents run autonomously after a single sign-off." },
            { p: "So the 2026 question isn't \u201Ccan I speak a trade?\u201D It's \u201Cdoes the agent need my approval?\u201D And the industry has split down the middle." },
            { h: "The fear everyone names isn't the one that actually happened" },
            { p: "No public case has been found of a voice trade misexecuted because the machine misheard. Zero. The documented disasters are different. In 2017, a 6-year-old's Echo ordered a ~$170 dollhouse and four pounds of sugar cookies \u2014 and a TV anchor retelling the story triggered viewers' Echos to try ordering too. In 2026, attackers combined a cloned voice with spoofed WhatsApp messages and got a bank chairman to wire roughly \u20AC95 million; around \u20AC36\u201339 million is still missing." },
            { p: "The failure mode isn't mishearing. It's impersonation. A spoken \u201Cyes\u201D is no longer proof it was you." },
            { h: "The numbers nobody publishes" },
            { p: "Webull says Vega reached roughly 480,000 active users by the end of June 2026. Robinhood says nearly 1 million customers used Cortex Digests, as of Q1 2026. One secondary source credits Robinhood's agentic trading with 150,000+ agent accounts \u2014 unverified. And the number that matters most: what fraction of orders actually originate by voice. No broker discloses it. No broker discloses voice-order error rates either." },
            { h: "Where this lands" },
            { p: "Voice is becoming an input box, not a product. The stable equilibrium is voice in, agent drafts, human confirms. Fully autonomous voice execution \u2014 speak and it's done, no screen \u2014 has no credible 2026 product and no regulatory path visible that our research could find. FINRA's 2026 report flagged AI agents under six risk headings, from autonomy to auditability \u2014 guidance, not rules." },
            { p: "The binding constraint was never transcription accuracy. It's trust and liability. Voice cloning made the spoken PIN unsafe on its own. The next voice-trading product has to solve provable identity plus non-repudiable confirmation first." },
            { p: "Your voice can already place a trade. The market just hasn't decided who pays when it hears you wrong." }
          ]
        }
      ];

      var listEl = document.getElementById("lib-list");
      var countEl = document.getElementById("lib-count");
      var filtersEl = document.getElementById("lib-filters");
      var noteEl = document.getElementById("lib-note");
      var activeFilter = "All";

      function esc(s) {
        return String(s)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
      }

      function entryNumber(i) {
        var n = LIBRARY.length - i;
        return (n < 10 ? "00" : n < 100 ? "0" : "") + n;
      }

      function renderFilters() {
        var types = ["All"];
        LIBRARY.forEach(function (e) {
          if (types.indexOf(e.type) === -1) types.push(e.type);
        });
        if (types.indexOf(activeFilter) === -1) activeFilter = "All";
        filtersEl.innerHTML = "";
        types.forEach(function (t) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "filter-btn";
          b.textContent = t === "All" ? "All" : t + "s";
          b.setAttribute("aria-pressed", t === activeFilter ? "true" : "false");
          b.addEventListener("click", function () {
            activeFilter = t;
            renderFilters();
            renderList();
          });
          filtersEl.appendChild(b);
        });
      }

      function renderList() {
        var shown = 0;
        listEl.innerHTML = "";
        LIBRARY.forEach(function (e, i) {
          if (activeFilter !== "All" && e.type !== activeFilter) return;
          shown++;
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "entry";
          btn.setAttribute("aria-haspopup", "dialog");
          btn.innerHTML =
            '<span class="eno">' + entryNumber(i) + "</span>" +
            "<span>" +
              '<span class="emeta"><span class="cat">' + esc(e.type) + "</span><span>" +
              esc(e.date) + "</span><span>" + e.mins + " min read</span></span>" +
              "<h3>" + esc(e.title) + "</h3>" +
              "<p>" + esc(e.excerpt) + "</p>" +
            "</span>" +
            '<span class="read">Read <span class="arr">\u2192</span></span>';
          btn.addEventListener("click", function () { openReader(e, entryNumber(i)); });
          listEl.appendChild(btn);
        });
        if (shown === 0) {
          var d = document.createElement("div");
          d.className = "lib-empty";
          d.textContent = "Nothing filed under this type yet.";
          listEl.appendChild(d);
        }
        countEl.textContent =
          LIBRARY.length + (LIBRARY.length === 1 ? " piece" : " pieces") + " in the archive";
        noteEl.textContent =
          LIBRARY.length === 1
            ? "Entry 001 is the first piece filed. Research reports from the lab and stories from across the units land here as they're finished."
            : "Research reports from the lab and stories from across the units land here as they're finished.";
      }

      /* ---------- Reader ---------- */
      var reader = document.getElementById("reader");
      var backdrop = document.getElementById("reader-backdrop");
      var readerBody = document.getElementById("reader-body");
      var readerKicker = document.getElementById("reader-kicker");
      var lastFocus = null;

      function openReader(e, no) {
        lastFocus = document.activeElement;
        readerKicker.textContent = "Library \u00B7 No. " + no;
        var html =
          '<div class="rmeta"><span class="cat">' + esc(e.type) + "</span><span>" +
          esc(e.date) + "</span><span>" + e.mins + " min read</span></div>" +
          '<h2 id="reader-title">' + esc(e.title) + "</h2>" +
          '<p class="dek">' + esc(e.dek) + '</p><div class="article">';
        e.body.forEach(function (b) {
          if (b.h) html += "<h3>" + esc(b.h) + "</h3>";
          else if (b.p) html += "<p>" + esc(b.p) + "</p>";
        });
        html += "</div>";
        readerBody.innerHTML = html;
        reader.scrollTop = 0;
        reader.classList.add("open");
        backdrop.classList.add("open");
        document.body.classList.add("locked");
        document.getElementById("reader-close").focus();
      }

      function closeReader() {
        reader.classList.remove("open");
        backdrop.classList.remove("open");
        document.body.classList.remove("locked");
        if (lastFocus && lastFocus.focus) lastFocus.focus();
      }

      document.getElementById("reader-close").addEventListener("click", closeReader);
      backdrop.addEventListener("click", closeReader);
      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && reader.classList.contains("open")) closeReader();
      });

      renderFilters();
      renderList();
