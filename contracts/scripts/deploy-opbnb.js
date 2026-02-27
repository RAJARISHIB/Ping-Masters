/**
 * deploy-opbnb.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Deploys the LiquidationArchive contract to opBNB Testnet and wires it up
 * by setting the FastAPI bot address as the authorised logger.
 *
 * Reads deployed-bsc.json for the deployer address (to keep things consistent).
 *
 * Usage:
 *   npm run deploy:opbnb
 *   # or
 *   npx hardhat run scripts/deploy-opbnb.js --network opBNBTestnet
 */

const { ethers } = require("hardhat");
const fs          = require("fs");
const path        = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("════════════════════════════════════════════════════════");
  console.log(" Ping-Masters — opBNB Testnet Deployment");
  console.log("════════════════════════════════════════════════════════");
  console.log("Deployer :", deployer.address);
  console.log(
    "Balance  :",
    ethers.formatEther(await ethers.provider.getBalance(deployer.address)),
    "BNB"
  );
  console.log("────────────────────────────────────────────────────────");

  // ── Deploy LiquidationArchive ─────────────────────────────────────────────
  console.log("\n[1/1] Deploying LiquidationArchive...");
  const Archive   = await ethers.getContractFactory("LiquidationArchive");
  const archive   = await Archive.deploy();
  await archive.waitForDeployment();
  const archiveAddr = await archive.getAddress();
  console.log("      ✔  LiquidationArchive:", archiveAddr);

  // ── Optionally set the logger bot ─────────────────────────────────────────
  const botAddress = process.env.LOGGER_BOT_ADDRESS;
  if (botAddress && ethers.isAddress(botAddress)) {
    console.log("\n[+] Setting logger bot to:", botAddress);
    const tx = await archive.setLoggerBot(botAddress);
    await tx.wait();
    console.log("      ✔  Logger bot set.");
  } else {
    console.log(
      "\n[!] LOGGER_BOT_ADDRESS not set in .env — skip setLoggerBot()."
    );
    console.log("    Set it later with:  archive.setLoggerBot(<bot-address>)");
  }

  // ── Save deployment addresses ─────────────────────────────────────────────
  const deployment = {
    network:        "opBNBTestnet",
    chainId:        5611,
    deployedAt:     new Date().toISOString(),
    deployer:       deployer.address,
    contracts: {
      LiquidationArchive: archiveAddr,
    },
    loggerBot: botAddress || "not-set",
  };

  const outPath = path.join(__dirname, "..", "deployed-opbnb.json");
  fs.writeFileSync(outPath, JSON.stringify(deployment, null, 2));
  console.log("\n[+] Address saved to deployed-opbnb.json");

  // ── Summary ───────────────────────────────────────────────────────────────
  console.log("\n════════════════════════════════════════════════════════");
  console.log(" Deployment complete!");
  console.log("════════════════════════════════════════════════════════");
  console.log(" LiquidationArchive :", archiveAddr);
  console.log("────────────────────────────────────────────────────────");
  console.log(" Next steps:");
  console.log("   1. Copy address to backend/.env as ARCHIVE_CONTRACT_ADDRESS");
  console.log("   2. Fund your FastAPI bot wallet with a tiny amount of BNB");
  console.log("      on opBNB Testnet for gas (fees are ~free).");
  console.log("   3. Start the FastAPI monitoring service.");
  console.log("════════════════════════════════════════════════════════\n");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
