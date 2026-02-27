// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./DebtToken.sol";
import "./PriceConsumer.sol";

/**
 * @title LendingEngine
 * @notice Core lending/borrowing/liquidation contract for Ping-Masters.
 *         Deployed on BNB Smart Chain Testnet.
 *
 * ═══════════════════════════════════════════════════════════════════
 *  DUAL CURRENCY SUPPORT
 * ═══════════════════════════════════════════════════════════════════
 *  Each user chooses USD or INR as their debt denomination.
 *  The FastAPI API passes the preference as:
 *    currency = 0  ->  USD  (mints pmUSD, uses BNB/USD price feed)
 *    currency = 1  ->  INR  (mints pmINR, uses BNB/INR price feed)
 *
 *  Currency can only be changed when the user has ZERO active debt.
 *
 * ═══════════════════════════════════════════════════════════════════
 *  MATH (no floating point)
 * ═══════════════════════════════════════════════════════════════════
 *  BNB collateral  ->  wei           (1 BNB  = 1e18)
 *  pmUSD / pmINR   ->  18 decimals   ($1=1e18  /  Rs1=1e18)
 *  Oracle price    ->  8 decimals    (Chainlink convention)
 *
 *  collateralValue = collateralWei * price / 1e8
 *
 *  healthFactor    = (collateralValue * LIQUIDATION_THRESHOLD * 1e18)
 *                    ──────────────────────────────────────────────
 *                              (borrowedAmount * 100)
 *
 *  HF >= 1e18  ->  SAFE          HF < 1e18  ->  LIQUIDATABLE
 */
contract LendingEngine {

    // ─── CONSTANTS ───────────────────────────────────────────────────────────

    uint256 public constant PRECISION             = 1e18;
    uint256 public constant PRICE_DECIMALS        = 1e8;
    uint256 public constant LIQUIDATION_THRESHOLD = 80;   // 80%
    uint256 public constant LIQUIDATION_BONUS     = 5;    // 5%
    uint256 public constant MAX_LTV               = 75;   // 75%

    PriceConsumer.Currency private constant USD = PriceConsumer.Currency.USD;
    PriceConsumer.Currency private constant INR = PriceConsumer.Currency.INR;

    // ─── STATE ───────────────────────────────────────────────────────────────

    /// @notice BNB deposited per user (wei).
    mapping(address => uint256) public collateralAmount;

    /// @notice Debt minted per user in their chosen currency (18-decimal).
    mapping(address => uint256) public borrowedAmount;

    /// @notice The currency (USD=0, INR=1) the user chose.
    mapping(address => PriceConsumer.Currency) public userCurrency;

    /// @notice True once the user has set a currency preference.
    mapping(address => bool) public hasCurrency;

    address[]                  public borrowers;
    mapping(address => bool)   private _isBorrower;

    DebtToken     public immutable debtTokenUSD;  // pmUSD
    DebtToken     public immutable debtTokenINR;  // pmINR
    PriceConsumer public immutable priceOracle;

    address public owner;
    bool    public paused;

    // ─── EVENTS ──────────────────────────────────────────────────────────────

    event CollateralDeposited(address indexed user, uint256 amount);
    event CollateralWithdrawn(address indexed user, uint256 amount);
    event CurrencySet(address indexed user, PriceConsumer.Currency currency);
    event Borrowed(address indexed user, uint256 amount, PriceConsumer.Currency currency);
    event Repaid(address indexed user, uint256 amount);
    event Liquidated(
        address indexed user,
        address indexed liquidator,
        uint256 debtRepaid,
        uint256 collateralSeized,
        uint256 bonus,
        PriceConsumer.Currency currency
    );
    event Paused(bool state);

    // ─── ERRORS ──────────────────────────────────────────────────────────────

    error NotOwner();
    error ContractPaused();
    error ZeroAmount();
    error InsufficientCollateral();
    error BorrowLimitExceeded();
    error PositionHealthy();
    error InsufficientDebtBalance();
    error CollateralTransferFailed();
    error WithdrawWouldLiquidate();
    error NoBorrowedDebt();
    error NoCurrencySet();
    error CurrencyLockedWhileInDebt();

    // ─── CONSTRUCTOR ─────────────────────────────────────────────────────────

    /**
     * @param _debtTokenUSD  Address of the pmUSD DebtToken.
     * @param _debtTokenINR  Address of the pmINR DebtToken.
     * @param _priceOracle   Address of the PriceConsumer.
     */
    constructor(
        address _debtTokenUSD,
        address _debtTokenINR,
        address _priceOracle
    ) {
        debtTokenUSD = DebtToken(_debtTokenUSD);
        debtTokenINR = DebtToken(_debtTokenINR);
        priceOracle  = PriceConsumer(_priceOracle);
        owner        = msg.sender;
    }

    // ─── MODIFIERS ───────────────────────────────────────────────────────────

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }
    modifier notPaused() {
        if (paused) revert ContractPaused();
        _;
    }

    // ─── USER ACTIONS ────────────────────────────────────────────────────────

    /**
     * @notice Deposit BNB as collateral.
     */
    function depositCollateral() external payable notPaused {
        if (msg.value == 0) revert ZeroAmount();
        collateralAmount[msg.sender] += msg.value;
        _trackBorrower(msg.sender);
        emit CollateralDeposited(msg.sender, msg.value);
    }

    /**
     * @notice Withdraw BNB collateral.
     *         Reverts if the withdrawal would make the position unhealthy.
     * @param  amount  Amount in wei.
     */
    function withdrawCollateral(uint256 amount) external notPaused {
        if (amount == 0)                              revert ZeroAmount();
        if (collateralAmount[msg.sender] < amount)    revert InsufficientCollateral();

        collateralAmount[msg.sender] -= amount;

        if (borrowedAmount[msg.sender] > 0) {
            if (_calculateHealthFactor(msg.sender) < PRECISION) {
                collateralAmount[msg.sender] += amount; // undo
                revert WithdrawWouldLiquidate();
            }
        }

        (bool ok, ) = payable(msg.sender).call{value: amount}("");
        if (!ok) revert CollateralTransferFailed();
        emit CollateralWithdrawn(msg.sender, amount);
    }

    /**
     * @notice Set or confirm the user's preferred debt currency.
     *         Can only be changed when the user has zero outstanding debt.
     *
     *         The FastAPI backend calls this on user registration or after
     *         the user fully repays and wants to switch currency.
     *
     * @param  currency  PriceConsumer.Currency.USD (0)  or  .INR (1)
     */
    function setCurrency(PriceConsumer.Currency currency) external notPaused {
        if (borrowedAmount[msg.sender] > 0) revert CurrencyLockedWhileInDebt();
        userCurrency[msg.sender] = currency;
        hasCurrency[msg.sender]  = true;
        _trackBorrower(msg.sender);
        emit CurrencySet(msg.sender, currency);
    }

    /**
     * @notice Borrow using the user's pre-set currency.
     *         Call setCurrency() first, or use borrow(amount, currency).
     * @param  amount  Debt to mint in the user's denomination (18-decimal).
     */
    function borrow(uint256 amount) external notPaused {
        if (amount == 0)                              revert ZeroAmount();
        if (collateralAmount[msg.sender] == 0)        revert InsufficientCollateral();
        if (!hasCurrency[msg.sender])                 revert NoCurrencySet();

        _executeBorrow(msg.sender, amount, userCurrency[msg.sender]);
    }

    /**
     * @notice Set currency AND borrow in one transaction.
     *         Designed for first-time borrowers; the FastAPI API call passes
     *         the user's chosen currency from the request body.
     *
     * @param  amount    Debt amount (18-decimal).
     * @param  currency  PriceConsumer.Currency.USD (0)  or  .INR (1)
     */
    function borrow(
        uint256 amount,
        PriceConsumer.Currency currency
    ) external notPaused {
        if (amount == 0)                 revert ZeroAmount();
        if (collateralAmount[msg.sender] == 0) revert InsufficientCollateral();

        // Switching currency mid-debt is not allowed
        if (borrowedAmount[msg.sender] > 0 &&
            userCurrency[msg.sender] != currency)
            revert CurrencyLockedWhileInDebt();

        if (!hasCurrency[msg.sender] || userCurrency[msg.sender] != currency) {
            userCurrency[msg.sender] = currency;
            hasCurrency[msg.sender]  = true;
            emit CurrencySet(msg.sender, currency);
        }

        _executeBorrow(msg.sender, amount, currency);
    }

    /**
     * @notice Repay outstanding debt (pmUSD or pmINR depending on user's currency).
     * @param  amount  Amount to repay (18-decimal).
     */
    function repay(uint256 amount) external notPaused {
        if (amount == 0) revert ZeroAmount();
        uint256 debt = borrowedAmount[msg.sender];
        if (debt == 0)   revert NoBorrowedDebt();

        uint256 toRepay = amount > debt ? debt : amount;
        borrowedAmount[msg.sender] -= toRepay;
        _getDebtToken(userCurrency[msg.sender]).burn(msg.sender, toRepay);
        emit Repaid(msg.sender, toRepay);
    }

    // ─── LIQUIDATION ─────────────────────────────────────────────────────────

    /**
     * @notice Liquidate an unhealthy position.
     *
     *  Flow:
     *   1. Verify healthFactor < 1e18.
     *   2. Burn the full outstanding pmUSD or pmINR from the liquidator.
     *   3. Transfer (debtInBNB + 5% bonus) BNB to the liquidator.
     *
     *  The liquidator must hold sufficient pmUSD or pmINR before calling.
     *
     * @param  user  The under-collateralised borrower's address.
     */
    function liquidate(address user) external notPaused {
        uint256 hf = _calculateHealthFactor(user);
        if (hf >= PRECISION) revert PositionHealthy();

        uint256 debt = borrowedAmount[user];
        if (debt == 0) revert NoBorrowedDebt();

        PriceConsumer.Currency cur = userCurrency[user];
        DebtToken token = _getDebtToken(cur);

        if (token.balanceOf(msg.sender) < debt) revert InsufficientDebtBalance();

        uint256 price      = priceOracle.getLatestPrice(cur);
        // debtInBNB = debt(fiat-wei) * PRICE_DECIMALS / price(8-dec) -> BNB-wei
        uint256 debtInBNB  = (debt * PRICE_DECIMALS) / price;
        uint256 bonus      = (debtInBNB * LIQUIDATION_BONUS) / 100;
        uint256 totalSeize = debtInBNB + bonus;

        uint256 userCol = collateralAmount[user];
        if (totalSeize > userCol) totalSeize = userCol;

        // State changes BEFORE external calls (CEI pattern)
        borrowedAmount[user]    = 0;
        collateralAmount[user] -= totalSeize;

        token.burn(msg.sender, debt);

        (bool ok, ) = payable(msg.sender).call{value: totalSeize}("");
        if (!ok) revert CollateralTransferFailed();

        emit Liquidated(user, msg.sender, debt, totalSeize, bonus, cur);
    }

    // ─── VIEW ─────────────────────────────────────────────────────────────────

    /**
     * @notice Full position snapshot — called by the FastAPI bot every ~3 s.
     *
     * @return collateralBNB    BNB deposited (wei).
     * @return collateralFiat   Collateral value in user's currency (18-dec).
     * @return debt             Outstanding debt (18-dec).
     * @return healthFactor     Scaled by 1e18. >= 1e18 = safe.
     * @return isLiquidatable   True when healthFactor < 1e18.
     * @return currency         PriceConsumer.Currency (0=USD, 1=INR).
     */
    function getAccountStatus(address user)
        external
        view
        returns (
            uint256 collateralBNB,
            uint256 collateralFiat,
            uint256 debt,
            uint256 healthFactor,
            bool    isLiquidatable,
            PriceConsumer.Currency currency
        )
    {
        currency       = hasCurrency[user] ? userCurrency[user] : USD;
        uint256 price  = priceOracle.getLatestPrice(currency);
        collateralBNB  = collateralAmount[user];
        collateralFiat = _toFiatValue(collateralBNB, price);
        debt           = borrowedAmount[user];
        healthFactor   = debt == 0 ? type(uint256).max : _calculateHealthFactor(user);
        isLiquidatable = healthFactor < PRECISION;
    }

    /// @notice Maximum additional debt the user can borrow right now.
    function getBorrowCapacity(address user) external view returns (uint256) {
        if (!hasCurrency[user]) return 0;
        uint256 price     = priceOracle.getLatestPrice(userCurrency[user]);
        uint256 colFiat   = _toFiatValue(collateralAmount[user], price);
        uint256 maxBorrow = (colFiat * MAX_LTV) / 100;
        uint256 current   = borrowedAmount[user];
        return maxBorrow > current ? maxBorrow - current : 0;
    }

    function getBorrowers()     external view returns (address[] memory) { return borrowers; }
    function getBorrowerCount() external view returns (uint256)          { return borrowers.length; }

    // ─── INTERNAL ────────────────────────────────────────────────────────────

    function _executeBorrow(
        address user,
        uint256 amount,
        PriceConsumer.Currency currency
    ) internal {
        uint256 price     = priceOracle.getLatestPrice(currency);
        uint256 colFiat   = _toFiatValue(collateralAmount[user], price);
        uint256 maxBorrow = (colFiat * MAX_LTV) / 100;
        uint256 newDebt   = borrowedAmount[user] + amount;
        if (newDebt > maxBorrow) revert BorrowLimitExceeded();

        borrowedAmount[user] += amount;
        _trackBorrower(user);
        _getDebtToken(currency).mint(user, amount);
        emit Borrowed(user, amount, currency);
    }

    function _calculateHealthFactor(address user) internal view returns (uint256) {
        uint256 debt = borrowedAmount[user];
        if (debt == 0) return type(uint256).max;
        PriceConsumer.Currency cur = userCurrency[user];
        uint256 price   = priceOracle.getLatestPrice(cur);
        uint256 colFiat = _toFiatValue(collateralAmount[user], price);
        // HF = (colFiat * THRESHOLD * PRECISION) / (debt * 100)
        return (colFiat * LIQUIDATION_THRESHOLD * PRECISION) / (debt * 100);
    }

    /// @dev BNB (wei) -> fiat value with 18 decimal places (same as pmUSD/pmINR).
    function _toFiatValue(uint256 bnbWei, uint256 price) internal pure returns (uint256) {
        return (bnbWei * price) / PRICE_DECIMALS;
    }

    /// @dev Returns the correct debt token for the given currency.
    function _getDebtToken(PriceConsumer.Currency cur) internal view returns (DebtToken) {
        return cur == USD ? debtTokenUSD : debtTokenINR;
    }

    function _trackBorrower(address user) internal {
        if (!_isBorrower[user]) {
            _isBorrower[user] = true;
            borrowers.push(user);
        }
    }

    // ─── ADMIN ───────────────────────────────────────────────────────────────

    function setPaused(bool _paused) external onlyOwner {
        paused = _paused;
        emit Paused(_paused);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        owner = newOwner;
    }

    receive() external payable {
        if (msg.value > 0) {
            collateralAmount[msg.sender] += msg.value;
            _trackBorrower(msg.sender);
            emit CollateralDeposited(msg.sender, msg.value);
        }
    }
}
