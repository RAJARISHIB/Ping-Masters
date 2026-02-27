require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

const PRIVATE_KEY  = process.env.DEPLOYER_PRIVATE_KEY  || "0x" + "0".repeat(64);
const BSC_API_KEY  = process.env.BSCSCAN_API_KEY        || "";

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,          // balanced between deployment cost and call cost
      },
      // Enable IR pipeline for complex contracts (prevents "stack too deep")
      viaIR: false,
    },
  },

  // ─── Networks ─────────────────────────────────────────────────────────────
  networks: {
    // ── Local development ───────────────────────────────────────────────────
    hardhat: {
      chainId: 31337,
    },

    // ── BNB Smart Chain Testnet ──────────────────────────────────────────────
    // Contracts: PriceConsumer, DebtToken, LendingEngine
    bscTestnet: {
      url: process.env.BSC_TESTNET_RPC || "https://data-seed-prebsc-1-s1.binance.org:8545",
      chainId: 97,
      accounts: [PRIVATE_KEY],
      gasPrice: 10_000_000_000,   // 10 gwei
    },

    // ── opBNB Testnet ────────────────────────────────────────────────────────
    // Contracts: LiquidationArchive
    opBNBTestnet: {
      url: process.env.OPBNB_TESTNET_RPC || "https://opbnb-testnet-rpc.bnbchain.org",
      chainId: 5611,
      accounts: [PRIVATE_KEY],
      gasPrice: 1_000_000,        // ~0.001 gwei — opBNB is ultra-cheap
    },
  },

  // ─── Block Explorer Verification ─────────────────────────────────────────
  etherscan: {
    apiKey: {
      bscTestnet:    BSC_API_KEY,
      opBNBTestnet:  process.env.OPBNB_API_KEY || "",
    },
    customChains: [
      {
        network:    "opBNBTestnet",
        chainId:    5611,
        urls: {
          apiURL:     "https://open-platform.nodereal.io/v1/opbnb-testnet/contract/",
          browserURL: "https://testnet.opbnbscan.com",
        },
      },
    ],
  },

  // ─── Gas Reporter (optional) ─────────────────────────────────────────────
  gasReporter: {
    enabled:     process.env.REPORT_GAS === "true",
    currency:    "USD",
    coinmarketcap: process.env.COINMARKETCAP_API_KEY || "",
  },

  // ─── Paths ────────────────────────────────────────────────────────────────
  paths: {
    sources:   "./src",
    tests:     "./test",
    cache:     "./cache",
    artifacts: "./artifacts",
  },
};
