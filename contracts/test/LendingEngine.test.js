/**
 * test/LendingEngine.test.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Hardhat / Mocha / Chai tests — dual-currency (USD + INR) Ping-Masters.
 * Run:  npx hardhat test
 */

const { expect }  = require("chai");
const { ethers }  = require("hardhat");

// ── Currency enum values (must match PriceConsumer.Currency) ─────────────────
const USD = 0;
const INR = 1;

// ── Oracle seed prices (8 decimals) ──────────────────────────────────────────
const BNB_USD_PRICE = 300_00000000n;      // $300.00
const BNB_INR_PRICE = 2_500_000_000_000n; // Rs25000.00

// ── Helpers ───────────────────────────────────────────────────────────────────
async function deployAll() {
  const [owner, alice, bob, liquidator] = await ethers.getSigners();

  // 1. PriceConsumer (dual feed)
  const PriceConsumer = await ethers.getContractFactory("PriceConsumer");
  const oracle        = await PriceConsumer.deploy(BNB_USD_PRICE, BNB_INR_PRICE);

  // 2. DebtToken x2
  const DebtToken = await ethers.getContractFactory("DebtToken");
  const pmUSD     = await DebtToken.deploy("Ping-Masters USD", "pmUSD");
  const pmINR     = await DebtToken.deploy("Ping-Masters INR", "pmINR");

  // 3. LendingEngine (three args now)
  const LendingEngine = await ethers.getContractFactory("LendingEngine");
  const engine        = await LendingEngine.deploy(
    await pmUSD.getAddress(),
    await pmINR.getAddress(),
    await oracle.getAddress()
  );

  // 4. Wire both minters
  await pmUSD.setMinter(await engine.getAddress());
  await pmINR.setMinter(await engine.getAddress());

  // 5. LiquidationArchive
  const Archive = await ethers.getContractFactory("LiquidationArchive");
  const archive = await Archive.deploy();

  return { owner, alice, bob, liquidator, oracle, pmUSD, pmINR, engine, archive };
}

// ── PriceConsumer ─────────────────────────────────────────────────────────────
describe("PriceConsumer — dual currency", function () {
  it("returns correct initial USD price", async function () {
    const { oracle } = await deployAll();
    expect(await oracle["getLatestPrice(uint8)"](USD)).to.equal(BNB_USD_PRICE);
  });

  it("returns correct initial INR price", async function () {
    const { oracle } = await deployAll();
    expect(await oracle["getLatestPrice(uint8)"](INR)).to.equal(BNB_INR_PRICE);
  });

  it("getBothPrices returns both feeds", async function () {
    const { oracle } = await deployAll();
    const [usd, inr] = await oracle.getBothPrices();
    expect(usd).to.equal(BNB_USD_PRICE);
    expect(inr).to.equal(BNB_INR_PRICE);
  });

  it("updateBothPrices updates atomically", async function () {
    const { oracle } = await deployAll();
    const newUSD = 400_00000000n;
    const newINR = 3_300_000_000_000n;
    await oracle.updateBothPrices(newUSD, newINR);
    const [u, i] = await oracle.getBothPrices();
    expect(u).to.equal(newUSD);
    expect(i).to.equal(newINR);
  });

  it("updatePrice updates a single currency", async function () {
    const { oracle } = await deployAll();
    await oracle["updatePrice(uint8,uint256)"](USD, 350_00000000n);
    expect(await oracle["getLatestPrice(uint8)"](USD)).to.equal(350_00000000n);
    expect(await oracle["getLatestPrice(uint8)"](INR)).to.equal(BNB_INR_PRICE); // unchanged
  });

  it("reverts if non-owner updates price", async function () {
    const { oracle, alice } = await deployAll();
    await expect(oracle.connect(alice).updateBothPrices(1n, 1n))
      .to.be.revertedWithCustomError(oracle, "Unauthorized");
  });
});

// ── DebtToken ──────────────────────────────────────────────────────────────────
describe("DebtToken — generic name/symbol", function () {
  it("pmUSD has correct metadata", async function () {
    const { pmUSD } = await deployAll();
    expect(await pmUSD.name()).to.equal("Ping-Masters USD");
    expect(await pmUSD.symbol()).to.equal("pmUSD");
  });

  it("pmINR has correct metadata", async function () {
    const { pmINR } = await deployAll();
    expect(await pmINR.name()).to.equal("Ping-Masters INR");
    expect(await pmINR.symbol()).to.equal("pmINR");
  });

  it("only minter can mint pmINR", async function () {
    const { pmINR, alice } = await deployAll();
    await expect(pmINR.connect(alice).mint(alice.address, 1n))
      .to.be.revertedWithCustomError(pmINR, "Unauthorized");
  });
});

// ── LendingEngine — USD borrowing ─────────────────────────────────────────────
describe("LendingEngine — USD borrowing", function () {
  it("mints pmUSD when currency=0", async function () {
    const { engine, pmUSD, alice } = await deployAll();
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    // 1 BNB @ $300, 75% LTV = $225 max
    const borrow = ethers.parseUnits("200", 18);  // $200
    await engine.connect(alice)["borrow(uint256,uint8)"](borrow, USD);
    expect(await pmUSD.balanceOf(alice.address)).to.equal(borrow);
  });

  it("health factor is correct for USD position", async function () {
    const { engine, alice } = await deployAll();
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    await engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("200", 18), USD);
    // HF = (300e18 * 80 * 1e18) / (200e18 * 100) = 1.2e18
    const { healthFactor } = await engine.getAccountStatus(alice.address);
    expect(healthFactor).to.equal(ethers.parseUnits("1.2", 18));
  });
});

// ── LendingEngine — INR borrowing ─────────────────────────────────────────────
describe("LendingEngine — INR borrowing", function () {
  it("mints pmINR when currency=1", async function () {
    const { engine, pmINR, alice } = await deployAll();
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    // 1 BNB @ Rs25000, 75% LTV = Rs18750 max
    const borrow = ethers.parseUnits("10000", 18); // Rs10000 < Rs18750
    await engine.connect(alice)["borrow(uint256,uint8)"](borrow, INR);
    expect(await pmINR.balanceOf(alice.address)).to.equal(borrow);
  });

  it("healthFactor uses INR oracle for INR borrowers", async function () {
    const { engine, alice } = await deployAll();
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    // Borrow Rs10000 against Rs25000 collateral
    // HF = (25000e18 * 80 * 1e18) / (10000e18 * 100) = 2.0e18
    await engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("10000", 18), INR);
    const { healthFactor } = await engine.getAccountStatus(alice.address);
    expect(healthFactor).to.equal(ethers.parseUnits("2.0", 18));
  });

  it("getAccountStatus returns correct currency for INR user", async function () {
    const { engine, alice } = await deployAll();
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    await engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("10000", 18), INR);
    const status = await engine.getAccountStatus(alice.address);
    expect(status.currency).to.equal(INR);
  });
});

// ── LendingEngine — currency switch ──────────────────────────────────────────
describe("LendingEngine — currency switching", function () {
  it("allows switching currency when debt is zero", async function () {
    const { engine, alice } = await deployAll();
    await engine.connect(alice).setCurrency(USD);
    await engine.connect(alice).setCurrency(INR); // can switch freely with no debt
    const status = await engine.getAccountStatus(alice.address);
    expect(status.currency).to.equal(INR);
  });

  it("blocks switching currency while in debt", async function () {
    const { engine, alice } = await deployAll();
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    await engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("100", 18), USD);
    // Try to borrow again with different currency (= switch while in debt)
    await expect(
      engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("100", 18), INR)
    ).to.be.revertedWithCustomError(engine, "CurrencyLockedWhileInDebt");
  });
});

// ── LendingEngine — liquidation (USD) ────────────────────────────────────────
describe("LendingEngine — liquidation", function () {
  it("liquidates unhealthy USD position and pays BNB bonus", async function () {
    const { engine, oracle, pmUSD, alice, liquidator } = await deployAll();

    // Alice borrows at max LTV: 1 BNB @ $300 -> borrows $225
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    await engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("225", 18), USD);

    // Price drops to $200 -> HF < 1
    await oracle["updatePrice(uint8,uint256)"](USD, 200_00000000n);

    // Give liquidator pmUSD (they deposit + borrow)
    await engine.connect(liquidator).depositCollateral({ value: ethers.parseEther("5") });
    await engine.connect(liquidator)["borrow(uint256,uint8)"](ethers.parseUnits("225", 18), USD);

    await engine.connect(liquidator).liquidate(alice.address);

    expect(await engine.borrowedAmount(alice.address)).to.equal(0n);
  });

  it("liquidates unhealthy INR position correctly", async function () {
    const { engine, oracle, pmINR, alice, liquidator } = await deployAll();

    // Alice borrows Rs18000 against 1 BNB (= Rs25000 collateral) — close to limit
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("1") });
    await engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("18000", 18), INR);

    // Price drops to Rs20000 -> HF = (20000 * 80 * 1e18) / (18000 * 100) ≈ 0.889 < 1
    await oracle["updatePrice(uint8,uint256)"](INR, 2_000_000_000_000n);

    // Give liquidator pmINR
    await engine.connect(liquidator).depositCollateral({ value: ethers.parseEther("5") });
    await engine.connect(liquidator)["borrow(uint256,uint8)"](ethers.parseUnits("18000", 18), INR);

    await engine.connect(liquidator).liquidate(alice.address);
    expect(await engine.borrowedAmount(alice.address)).to.equal(0n);
  });

  it("reverts liquidation of healthy position", async function () {
    const { engine, alice } = await deployAll();
    await engine.connect(alice).depositCollateral({ value: ethers.parseEther("2") });
    await engine.connect(alice)["borrow(uint256,uint8)"](ethers.parseUnits("100", 18), USD);
    await expect(engine.liquidate(alice.address))
      .to.be.revertedWithCustomError(engine, "PositionHealthy");
  });
});

// ── LiquidationArchive ───────────────────────────────────────────────────────
describe("LiquidationArchive — currency tracking", function () {
  it("stores USD liquidation and updates USD stats", async function () {
    const { archive, alice, bob, owner } = await deployAll();
    const debt  = ethers.parseUnits("225", 18);
    const seize = ethers.parseEther("1.18125");
    const bonus = ethers.parseEther("0.05625");

    await archive.connect(owner).logLiquidation(
      alice.address, bob.address,
      debt, seize, bonus,
      0,                // currency = USD
      10_000_000n,
      ethers.ZeroHash
    );

    const stats = await archive.getGlobalStats();
    expect(stats.totalEvents).to.equal(1n);
    expect(stats.totalUSD).to.equal(debt);
    expect(stats.totalINR).to.equal(0n);
  });

  it("stores INR liquidation and updates INR stats", async function () {
    const { archive, alice, bob, owner } = await deployAll();
    const debt = ethers.parseUnits("18000", 18);

    await archive.connect(owner).logLiquidation(
      alice.address, bob.address,
      debt, 1n, 0n,
      1,                // currency = INR
      10_000_001n,
      ethers.ZeroHash
    );

    const stats = await archive.getGlobalStats();
    expect(stats.totalINR).to.equal(debt);
    expect(stats.totalUSD).to.equal(0n);
  });

  it("reverts on invalid currency value", async function () {
    const { archive, alice, bob, owner } = await deployAll();
    await expect(
      archive.connect(owner).logLiquidation(
        alice.address, bob.address,
        1n, 1n, 0n, 2, 1n, ethers.ZeroHash  // currency = 2 is invalid
      )
    ).to.be.revertedWithCustomError(archive, "InvalidCurrency");
  });

  it("only authorised accounts can log", async function () {
    const { archive, alice } = await deployAll();
    await expect(
      archive.connect(alice).logLiquidation(
        alice.address, alice.address,
        1n, 1n, 0n, 0, 1n, ethers.ZeroHash
      )
    ).to.be.revertedWithCustomError(archive, "Unauthorized");
  });
});


