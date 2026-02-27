/**
 * deploy-bsc.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Deploys the four core contracts to BNB Smart Chain Testnet in order:
 *   1. PriceConsumer  — dual BNB/USD + BNB/INR price oracle
 *   2. DebtToken(pmUSD) — USD stablecoin
 *   3. DebtToken(pmINR) — INR stablecoin
 *   4. LendingEngine   — core lending / borrowing / liquidation logic
 *
 * After deployment:
 *   • LendingEngine is set as the minter on BOTH DebtToken contracts.
 *   • Deployed addresses are written to ../deployed-bsc.json
 *
 * Usage:
 *   npm run deploy:bsc
 */

const { ethers } = require("hardhat");
const fs          = require("fs");
const path        = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("═══════════════════════════════════════════════════════");
  console.log(" Ping-Masters — BSC Testnet Deployment (Dual Currency)");
  console.log("═══════════════════════════════════════════════════════");
  console.log("Deployer :", deployer.address);
  console.log(
    "Balance  :",
    ethers.formatEther(await ethers.provider.getBalance(deployer.address)),
    "BNB"
  );
  console.log("───────────────────────────────────────────────────────");

  // ── 1. PriceConsumer ──────────────────────────────────────────────────────
  // BNB/USD $300.00  ->  30_000_000_000  (8 decimals)
  // BNB/INR Rs25000  ->  2_500_000_000_000  (8 decimals)
  const INITIAL_USD = 30_000_000_000n;
  const INITIAL_INR = 2_500_000_000_000n;

  console.log("\n[1/4] Deploying PriceConsumer (USD + INR feeds)...");
  const PriceConsumer = await ethers.getContractFactory("PriceConsumer");
  const priceConsumer = await PriceConsumer.deploy(INITIAL_USD, INITIAL_INR);
  await priceConsumer.waitForDeployment();
  const priceAddr     = await priceConsumer.getAddress();
  console.log("      ✔  PriceConsumer:", priceAddr);

  // ── 2. DebtToken — pmUSD ─────────────────────────────────────────────────
  console.log("\n[2/4] Deploying DebtToken (pmUSD)...");
  const DebtToken  = await ethers.getContractFactory("DebtToken");
  const pmUSD      = await DebtToken.deploy("Ping-Masters USD", "pmUSD");
  await pmUSD.waitForDeployment();
  const pmUSDAddr  = await pmUSD.getAddress();
  console.log("      ✔  pmUSD:", pmUSDAddr);

  // ── 3. DebtToken — pmINR ─────────────────────────────────────────────────
  console.log("\n[3/4] Deploying DebtToken (pmINR)...");
  const pmINR     = await DebtToken.deploy("Ping-Masters INR", "pmINR");
  await pmINR.waitForDeployment();
  const pmINRAddr = await pmINR.getAddress();
  console.log("      ✔  pmINR:", pmINRAddr);

  // ── 4. LendingEngine ─────────────────────────────────────────────────────
  console.log("\n[4/4] Deploying LendingEngine...");
  const LendingEngine = await ethers.getContractFactory("LendingEngine");
  const lendingEngine = await LendingEngine.deploy(pmUSDAddr, pmINRAddr, priceAddr);
  await lendingEngine.waitForDeployment();
  const lendingAddr   = await lendingEngine.getAddress();
  console.log("      ✔  LendingEngine:", lendingAddr);

  // ── Set LendingEngine as minter on both tokens ───────────────────────────
  console.log("\n[+] Setting LendingEngine as minter on pmUSD...");
  await (await pmUSD.setMinter(lendingAddr)).wait();
  console.log("      ✔  pmUSD minter set.");

  console.log("[+] Setting LendingEngine as minter on pmINR...");
  await (await pmINR.setMinter(lendingAddr)).wait();
  console.log("      ✔  pmINR minter set.");

  // ── Save deployment addresses ─────────────────────────────────────────────
  const deployment = {
    network:    "bscTestnet",
    chainId:    97,
    deployedAt: new Date().toISOString(),
    deployer:   deployer.address,
    contracts: {
      PriceConsumer: priceAddr,
      DebtToken_pmUSD: pmUSDAddr,
      DebtToken_pmINR: pmINRAddr,
      LendingEngine:   lendingAddr,
    },
  };

  const outPath = path.join(__dirname, "..", "deployed-bsc.json");
  fs.writeFileSync(outPath, JSON.stringify(deployment, null, 2));
  console.log("\n[+] Addresses saved to deployed-bsc.json");

  // ── Summary ───────────────────────────────────────────────────────────────
  console.log("\n═══════════════════════════════════════════════════════");
  console.log(" Deployment complete!");
  console.log("═══════════════════════════════════════════════════════");
  console.log(" PriceConsumer  :", priceAddr);
  console.log(" pmUSD          :", pmUSDAddr);
  console.log(" pmINR          :", pmINRAddr);
  console.log(" LendingEngine  :", lendingAddr);
  console.log("───────────────────────────────────────────────────────");
  console.log(" Next steps:");
  console.log("   1. Copy addresses to backend/.env");
  console.log("   2. Run:  npm run deploy:opbnb");
  console.log("   3. Start FastAPI bot");
  console.log("═══════════════════════════════════════════════════════\n");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
